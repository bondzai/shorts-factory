"""Thin wrapper around the Anthropic SDK.

Every agent in this project calls Claude through `parse` (structured output) or
`write` (free text). Both return the dollar cost of the call so the pipeline can
store cost per clip — you want that number long before you want a nicer prompt.

Each agent can run on its own model. They are not the same job: the Analyst
reasons over a table of numbers, QC scores a hook from four frames, Idea picks a
variant and a seed. Pricing is per model, so the cost figure stays true when
they differ.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from . import settings

T = TypeVar("T", bound=BaseModel)


class Refused(RuntimeError):
    """Claude declined the request. Never retried automatically."""


@lru_cache(maxsize=1)
def client() -> anthropic.Anthropic:
    # Resolves ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN, then an
    # `ant auth login` profile. Do not pass a key in here.
    settings.load_env()
    return anthropic.Anthropic()


def has_credentials() -> bool:
    """Whether the built-in agents can run at all.

    Constructing the client never fails; only a resolved key or token means a
    call will. The page uses this to show the built-in agents' buttons only
    when pressing them could do something, and the Codex path otherwise.
    """
    try:
        c = client()
        return bool(c.api_key or c.auth_token)
    except Exception:
        return False


def model_for(agent: str | None) -> str:
    """Which model an agent runs on. Falls back to the shared default."""
    cfg = settings.load().llm
    if agent:
        chosen = cfg.get("agents", {}).get(agent)
        if chosen:
            return chosen
    return cfg["model"]


def price_of(model: str) -> tuple[float, float]:
    """(input, output) USD per million tokens, and whether it was a guess."""
    pricing = settings.load().llm.get("pricing", {})
    rate = pricing.get(model) or pricing.get("default") or [5.0, 25.0]
    return float(rate[0]), float(rate[1])


def usd(usage: Any, model: str) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    input_rate, output_rate = price_of(model)
    return inp / 1_000_000 * input_rate + out / 1_000_000 * output_rate


def _check(response: Any) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        raise Refused(f"model declined the request (category={category})")


def image_blocks(pngs: list[bytes]) -> list[dict[str, Any]]:
    """PNG bytes -> image content blocks, for agents that need to see the render."""
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(png).decode("ascii"),
            },
        }
        for png in pngs
    ]


def _record(agent: str | None, response: Any, cost: float, model: str) -> None:
    if not agent:
        return
    from . import logs

    usage = getattr(response, "usage", None)
    priced = model in settings.load().llm.get("pricing", {})
    logs.event(
        "agent.call",
        agent=agent,
        model=model,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cost_usd=round(cost, 6),
        # An unlisted model is billed at the default rate; say so rather than
        # let a wrong number look authoritative.
        cost_estimated=not priced,
        stop_reason=getattr(response, "stop_reason", None),
    )


def parse(
    output_model: type[T],
    *,
    system: str,
    content: str | list[dict[str, Any]],
    max_tokens: int = 8000,
    agent: str | None = None,
) -> tuple[T, float]:
    """One structured call. Returns the validated model and what it cost."""
    model = model_for(agent)
    response = client().messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=output_model,
    )
    _check(response)
    cost = usd(response.usage, model)
    _record(agent, response, cost, model)
    return response.parsed_output, cost


def write(
    *,
    system: str,
    content: str | list[dict[str, Any]],
    max_tokens: int = 64000,
    effort: str = "high",
    agent: str | None = None,
) -> tuple[str, float]:
    """One free-text call, streamed so a long answer can't hit the HTTP timeout."""
    model = model_for(agent)
    with client().messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort},
    ) as stream:
        response = stream.get_final_message()
    _check(response)
    cost = usd(response.usage, model)
    _record(agent, response, cost, model)
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, cost
