"""The brains, behind one door.

Every built-in agent calls a model through `parse` (structured output) or
`write` (free text). Which model, and whose, is configuration — a provider
plus a model name per agent — not code. Two kinds of provider cover the
market:

  anthropic   the Anthropic SDK, with its native structured output
  openai      anything speaking the OpenAI chat API: OpenAI itself, Ollama and
              LM Studio on this machine, Groq, Gemini's compatible endpoint,
              OpenRouter. Structured output is "reply with JSON matching this
              schema", validated with pydantic and retried once with the
              validation error, which every one of them can do.

Both return the dollar cost of the call so the pipeline can store cost per
clip. A local model costs nothing and says so.

The external path — Codex or Claude Code over MCP — does not come through
here at all; it reads playbooks and calls the server's tools. This module is
only for the agents the factory runs itself.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from . import settings

T = TypeVar("T", bound=BaseModel)

AGENTS = ("idea", "metadata", "qc", "analyst")
NEEDS_VISION = {"qc"}  # QC judges four frames; a text-only model cannot do the job
KINDS = ("anthropic", "openai")
JSON_MODES = ("schema", "object", "none")


class Refused(RuntimeError):
    """The model declined the request. Never retried automatically."""


@dataclass(frozen=True)
class Provider:
    id: str
    kind: str = "openai"
    base_url: str | None = None
    api_key_env: str | None = None  # None: the endpoint needs no key (local)
    vision: bool = True
    json_mode: str = "object"
    models: tuple[str, ...] = ()
    free: bool = False

    def key_present(self) -> bool:
        settings.load_env()
        if self.kind == "anthropic":
            c = client()
            return bool(c.api_key or c.auth_token)
        if not self.api_key_env:
            return True
        return bool(os.environ.get(self.api_key_env))

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["models"] = list(self.models)
        return d


# What the Settings screen offers under "add a provider". The key stays in
# .env — the page only ever sees the variable's name and whether it is set.
PRESETS = [
    {"id": "anthropic", "kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY", "vision": True,
     "json_mode": "schema", "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]},
    {"id": "openai", "kind": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY",
     "vision": True, "json_mode": "schema", "models": ["gpt-5", "gpt-5-mini"]},
    {"id": "ollama", "kind": "openai", "base_url": "http://localhost:11434/v1", "api_key_env": None,
     "vision": True, "json_mode": "object", "models": ["qwen2.5vl:7b", "gemma3:12b", "llama3.2-vision"], "free": True},
    {"id": "lmstudio", "kind": "openai", "base_url": "http://localhost:1234/v1", "api_key_env": None,
     "vision": True, "json_mode": "object", "models": [], "free": True},
    {"id": "groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY",
     "vision": False, "json_mode": "object", "models": ["llama-3.3-70b-versatile"]},
    {"id": "gemini", "kind": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
     "api_key_env": "GEMINI_API_KEY", "vision": True, "json_mode": "schema", "models": ["gemini-2.5-flash", "gemini-2.5-pro"]},
    {"id": "openrouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
     "vision": True, "json_mode": "object", "models": []},
]
DEFAULT_PROVIDERS = [PRESETS[0]]


def _provider_from(raw: dict[str, Any]) -> Provider:
    kind = raw.get("kind", "openai")
    if kind not in KINDS:
        raise ValueError(f"provider {raw.get('id')!r}: kind must be one of {KINDS}")
    json_mode = raw.get("json_mode", "object")
    if json_mode not in JSON_MODES:
        raise ValueError(f"provider {raw.get('id')!r}: json_mode must be one of {JSON_MODES}")
    if not raw.get("id"):
        raise ValueError("a provider needs an id")
    if kind == "openai" and not raw.get("base_url"):
        raise ValueError(f"provider {raw['id']!r}: an openai-compatible provider needs a base_url")
    return Provider(
        id=raw["id"], kind=kind, base_url=raw.get("base_url") or None,
        api_key_env=raw.get("api_key_env") or None, vision=bool(raw.get("vision", True)),
        json_mode=json_mode, models=tuple(raw.get("models") or ()), free=bool(raw.get("free", False)),
    )


def providers() -> list[Provider]:
    raw = settings.load().llm.get("providers") or DEFAULT_PROVIDERS
    return [_provider_from(p) for p in raw]


def provider(provider_id: str) -> Provider:
    for p in providers():
        if p.id == provider_id:
            return p
    raise ValueError(f"no provider {provider_id!r}; have {[p.id for p in providers()]}")


def assignment(agent: str | None) -> str:
    """'provider/model' for an agent. A bare model name means Anthropic, as before."""
    cfg = settings.load().llm
    chosen = None
    if agent:
        chosen = (cfg.get("agents") or {}).get(agent)
    chosen = chosen or cfg["model"]
    return chosen if "/" in chosen else f"anthropic/{chosen}"


def resolve(agent: str | None) -> tuple[Provider, str]:
    pid, _, model = assignment(agent).partition("/")
    return provider(pid), model


def model_for(agent: str | None) -> str:
    return resolve(agent)[1]


def readiness() -> dict[str, dict[str, Any]]:
    """Per agent: where it would run and whether that can work right now."""
    out = {}
    for agent in AGENTS:
        try:
            p, model = resolve(agent)
        except ValueError as exc:
            out[agent] = {"ok": False, "why": str(exc)}
            continue
        why = None
        if not p.key_present():
            why = f"{p.api_key_env or 'credentials'} not set in .env"
        elif agent in NEEDS_VISION and not p.vision:
            why = f"{p.id} cannot see images; {agent} judges frames"
        out[agent] = {"ok": why is None, "provider": p.id, "model": model, "why": why,
                      "free": p.free or (p.kind == "openai" and not p.api_key_env)}
    return out


def has_credentials() -> bool:
    """Whether every built-in agent could run right now."""
    try:
        return all(r["ok"] for r in readiness().values())
    except Exception:
        return False


# --- clients ------------------------------------------------------------------

@lru_cache(maxsize=1)
def client() -> anthropic.Anthropic:
    # Resolves ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN, then an
    # `ant auth login` profile. Do not pass a key in here.
    settings.load_env()
    return anthropic.Anthropic()


@lru_cache(maxsize=8)
def _openai_client(p: Provider):
    import openai

    settings.load_env()
    key = os.environ.get(p.api_key_env) if p.api_key_env else None
    return openai.OpenAI(base_url=p.base_url, api_key=key or "local")


# --- pricing ------------------------------------------------------------------

def price_of(model: str) -> tuple[float, float]:
    """(input, output) USD per million tokens."""
    pricing = settings.load().llm.get("pricing", {})
    rate = pricing.get(model) or pricing.get("default") or [5.0, 25.0]
    return float(rate[0]), float(rate[1])


def usd(usage: Any, model: str, p: Provider | None = None) -> float:
    if p is not None and (p.free or (p.kind == "openai" and not p.api_key_env)):
        return 0.0
    inp, out = _tokens(usage)
    input_rate, output_rate = price_of(model)
    return inp / 1_000_000 * input_rate + out / 1_000_000 * output_rate


def _tokens(usage: Any) -> tuple[int, int]:
    inp = getattr(usage, "input_tokens", None)
    if inp is None:
        inp = getattr(usage, "prompt_tokens", 0)
    out = getattr(usage, "output_tokens", None)
    if out is None:
        out = getattr(usage, "completion_tokens", 0)
    return int(inp or 0), int(out or 0)


def _record(agent: str | None, usage: Any, cost: float, p: Provider, model: str, stop: Any) -> None:
    if not agent:
        return
    from . import logs

    inp, out = _tokens(usage)
    priced = model in settings.load().llm.get("pricing", {}) or cost == 0.0
    logs.event(
        "agent.call", agent=agent, provider=p.id, model=model,
        input_tokens=inp, output_tokens=out, cost_usd=round(cost, 6),
        # An unlisted paid model is billed at the default rate; say so rather
        # than let a wrong number look authoritative.
        cost_estimated=not priced, stop_reason=stop,
    )


# --- content ------------------------------------------------------------------

def image_blocks(pngs: list[bytes]) -> list[dict[str, Any]]:
    """PNG bytes -> image content blocks, for agents that need to see the render.

    Anthropic's shape; `_to_openai_content` translates when the provider needs it.
    """
    return [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.standard_b64encode(png).decode("ascii")}}
        for png in pngs
    ]


def _to_openai_content(content: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    out = []
    for block in content:
        if block.get("type") == "image":
            src = block["source"]
            out.append({"type": "image_url", "image_url": {
                "url": f"data:{src['media_type']};base64,{src['data']}"}})
        else:
            out.append({"type": "text", "text": block.get("text", "")})
    return out


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


# --- the two calls ------------------------------------------------------------

def _check(response: Any) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        raise Refused(f"model declined the request (category={getattr(details, 'category', None)})")


def parse(
    output_model: type[T], *, system: str, content: str | list[dict[str, Any]],
    max_tokens: int = 8000, agent: str | None = None,
) -> tuple[T, float]:
    """One structured call. Returns the validated model and what it cost."""
    p, model = resolve(agent)
    if agent in NEEDS_VISION and not p.vision:
        raise ValueError(f"{agent} needs a provider that can see images; {p.id} cannot")
    if p.kind == "anthropic":
        response = client().messages.parse(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}], output_format=output_model,
        )
        _check(response)
        cost = usd(response.usage, model, p)
        _record(agent, response.usage, cost, p, model, response.stop_reason)
        return response.parsed_output, cost
    return _parse_openai(p, model, output_model, system, content, max_tokens, agent)


def _parse_openai(p, model, output_model, system, content, max_tokens, agent):
    schema = output_model.model_json_schema()
    instructions = (
        f"{system}\n\nReply with a single JSON object and nothing else — no prose, "
        f"no code fence. It must match this JSON Schema:\n{json.dumps(schema)}"
    )
    kwargs: dict[str, Any] = {}
    if p.json_mode == "schema":
        kwargs["response_format"] = {"type": "json_schema", "json_schema": {
            "name": output_model.__name__, "schema": schema}}
    elif p.json_mode == "object":
        kwargs["response_format"] = {"type": "json_object"}
    messages = [{"role": "system", "content": instructions},
                {"role": "user", "content": _to_openai_content(content)}]
    total = 0.0
    last_error = None
    for attempt in range(2):
        response = _openai_client(p).chat.completions.create(
            model=model, messages=messages, max_tokens=max_tokens, **kwargs)
        text = (response.choices[0].message.content or "") if response.choices else ""
        cost = usd(getattr(response, "usage", None), model, p)
        total += cost
        _record(agent, getattr(response, "usage", None), cost, p, model,
                getattr(response.choices[0], "finish_reason", None) if response.choices else None)
        try:
            return output_model.model_validate_json(_strip_fences(text)), total
        except (ValidationError, ValueError) as exc:
            last_error = exc
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"That was not valid: {exc}\nReply again with only the JSON object."}]
    raise ValueError(f"{p.id}/{model} did not return valid {output_model.__name__}: {last_error}")


def write(
    *, system: str, content: str | list[dict[str, Any]], max_tokens: int = 64000,
    effort: str = "high", agent: str | None = None,
) -> tuple[str, float]:
    """One free-text call."""
    p, model = resolve(agent)
    return _write_with(p, model, system=system, content=content, max_tokens=max_tokens,
                       effort=effort, agent=agent)


def _write_with(p, model, *, system, content, max_tokens, effort="high", agent=None):
    if p.kind == "anthropic":
        # Streamed so a long answer can't hit the HTTP timeout.
        with client().messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": content}], output_config={"effort": effort},
        ) as stream:
            response = stream.get_final_message()
        _check(response)
        cost = usd(response.usage, model, p)
        _record(agent, response.usage, cost, p, model, response.stop_reason)
        return "".join(b.text for b in response.content if b.type == "text"), cost
    response = _openai_client(p).chat.completions.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": _to_openai_content(content)}],
    )
    text = (response.choices[0].message.content or "") if response.choices else ""
    cost = usd(getattr(response, "usage", None), model, p)
    _record(agent, getattr(response, "usage", None), cost, p, model,
            getattr(response.choices[0], "finish_reason", None) if response.choices else None)
    return text, cost


def test_provider(provider_id: str, model: str | None = None) -> dict[str, Any]:
    """A one-word round trip, so the Settings screen can say 'this works' before
    an agent finds out the hard way."""
    try:
        p = provider(provider_id)
        model = model or (p.models[0] if p.models else None)
        if not model:
            return {"ok": False, "error": "give a model name to test with"}
        if not p.key_present():
            return {"ok": False, "error": f"{p.api_key_env} is not set in .env"}
        started = time.monotonic()
        text, cost = _write_with(p, model, system="You are a health check.",
                                 content="Reply with the single word: ok", max_tokens=8)
        return {"ok": True, "model": model, "latency_ms": int((time.monotonic() - started) * 1000),
                "reply": text.strip()[:40], "cost_usd": round(cost, 6)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
