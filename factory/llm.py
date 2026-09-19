"""Thin wrapper around the Anthropic SDK.

Every agent in this project calls Claude through `parse` (structured output) or
`write` (free text). Both return the dollar cost of the call so the pipeline can
store cost per clip — you want that number long before you want a nicer prompt.
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


def _model() -> str:
    return settings.load().llm["model"]


def usd(usage: Any) -> float:
    cfg = settings.load().llm
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    return (
        inp / 1_000_000 * cfg["input_usd_per_mtok"]
        + out / 1_000_000 * cfg["output_usd_per_mtok"]
    )


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


def _record(agent: str | None, response: Any, cost: float) -> None:
    if not agent:
        return
    from . import logs

    usage = getattr(response, "usage", None)
    logs.event(
        "agent.call",
        agent=agent,
        model=getattr(response, "model", _model()),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cost_usd=round(cost, 6),
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
    response = client().messages.parse(
        model=_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=output_model,
    )
    _check(response)
    cost = usd(response.usage)
    _record(agent, response, cost)
    return response.parsed_output, cost


def write(
    *,
    system: str,
    content: str | list[dict[str, Any]],
    max_tokens: int = 64000,
    effort: str = "high",
) -> tuple[str, float]:
    """One free-text call, streamed so a long answer can't hit the HTTP timeout."""
    with client().messages.stream(
        model=_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort},
    ) as stream:
        response = stream.get_final_message()
    _check(response)
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, usd(response.usage)
