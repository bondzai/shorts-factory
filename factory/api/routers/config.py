"""Everything on the Settings screen: knobs, rules, directions, themes, brains."""

from __future__ import annotations

from datetime import date
from typing import Any
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import db
from ... import llm
from ... import logs
from ... import playbooks
from ... import settings
from ... import themes
from ...agents import analyst
from ..common import resolve

router = APIRouter()

def coerce(field: dict[str, Any], value: Any) -> Any:
    if field["type"] == "number":
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field['label']}: not a number") from None
        if "min" in field and value < field["min"] or "max" in field and value > field["max"]:
            raise ValueError(f"{field['label']}: must be between {field['min']} and {field['max']}")
        return int(value) if float(value).is_integer() and field.get("step", 1) == 1 else value
    if field["type"] == "select":
        for option in field["options"]:
            if str(option) == str(value):
                return option
        raise ValueError(f"{field['label']}: must be one of {field['options']}")
    return str(value)


def _settings_view() -> dict[str, Any]:
    cfg = settings.load()
    fields = []
    for f in settings.SCHEMA:
        key = (f["section"], f["key"])
        fields.append({
            **f,
            "value": cfg.raw.get(f["section"], {}).get(f["key"]),
            "default": cfg.base.get(f["section"], {}).get(f["key"]),
            "overridden": key in cfg.overrides,
        })
    return {"fields": fields}


@router.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return _settings_view()


class SettingBody(BaseModel):
    section: str
    key: str
    value: Any


@router.put("/api/settings")
def put_setting(body: SettingBody) -> dict[str, Any]:
    field = next((f for f in settings.SCHEMA if f["section"] == body.section and f["key"] == body.key), None)
    if field is None:
        raise HTTPException(404, f"no setting {body.section}.{body.key}")
    try:
        value = coerce(field, body.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    with db.connect() as conn:
        db.set_override(conn, body.section, body.key, value)
    settings.invalidate()
    logs.event("settings.changed", section=body.section, key=body.key, value=value, by="human")
    return _settings_view()


@router.delete("/api/settings/{section}/{key}")
def reset_setting(section: str, key: str) -> dict[str, Any]:
    with db.connect() as conn:
        db.clear_override(conn, section, key)
    settings.invalidate()
    logs.event("settings.reset", section=section, key=key, by="human")
    return _settings_view()


@router.get("/api/market")
def get_market(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        return {"channel": ch.id, "market": playbooks.market_for(conn, ch.id), "markets": playbooks.markets()}


class MarketBody(BaseModel):
    channel: str | None = None
    market: str


@router.put("/api/market")
def put_market(body: MarketBody) -> dict[str, Any]:
    if body.market and body.market not in playbooks.markets():
        raise HTTPException(400, f"no market brief {body.market!r}; have {playbooks.markets()} (add prompts/market-<id>.md)")
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        db.set_override(conn, "market", ch.id, body.market)
    logs.event("settings.changed", section="market", key=ch.id, market=body.market, by="human")
    return get_market(ch.id)


@router.get("/api/directions")
def get_directions(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        values = playbooks.directions(conn, ch.id)
    return {
        "channel": ch.id,
        "fields": [{"key": k, "label": label, "placeholder": hint, "value": values[k]} for k, label, hint in playbooks.DIRECTION_FIELDS],
    }


class DirectionsBody(BaseModel):
    channel: str | None = None
    values: dict[str, str]


@router.put("/api/directions")
def put_directions(body: DirectionsBody) -> dict[str, Any]:
    allowed = {k for k, _, _ in playbooks.DIRECTION_FIELDS}
    unknown = set(body.values) - allowed
    if unknown:
        raise HTTPException(400, f"no such direction: {sorted(unknown)}")
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        clean = {k: v.strip()[:600] for k, v in body.values.items()}
        db.set_override(conn, "directions", ch.id, clean)
    logs.event("settings.changed", section="directions", key=ch.id, by="human")
    return get_directions(ch.id)


def _themes_view() -> dict[str, Any]:

    today = date.today()
    cfg = settings.load()
    return {
        "themes": [t.as_dict() for t in themes.themes()],
        "active": themes.active(today).id,
        "today": today.isoformat(),
        "force": (cfg.raw.get("themes", {}).get("force") or ""),
        "decorations": list(themes.DECORATIONS),
        "overridden": ("themes", "list") in cfg.overrides or ("themes", "force") in cfg.overrides,
    }


@router.get("/api/themes")
def get_themes() -> dict[str, Any]:
    return _themes_view()


class ThemesBody(BaseModel):
    themes: list[dict[str, Any]]
    force: str = ""


@router.put("/api/themes")
def put_themes(body: ThemesBody) -> dict[str, Any]:
    try:
        parsed = [themes.from_dict(t) for t in body.themes]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    ids = [t.id for t in parsed]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "two themes share an id")
    if body.force and body.force not in ids and body.force != "default":
        raise HTTPException(400, f"cannot force {body.force!r}: not a theme here")
    with db.connect() as conn:
        db.set_override(conn, "themes", "list", [t.as_dict() for t in parsed])
        db.set_override(conn, "themes", "force", body.force)
    settings.invalidate()
    logs.event("settings.changed", section="themes", key="list", force=body.force, by="human")
    # Echo what was just saved rather than re-reading: the read is right too,
    # but the page should never see a stale value for the thing it just set.
    return {**_themes_view(), "themes": [t.as_dict() for t in parsed], "force": body.force, "overridden": True}


def _brains_view() -> dict[str, Any]:
    return {
        "providers": [{**p.as_dict(), "key_present": p.key_present()} for p in llm.providers()],
        "agents": {a: llm.assignment(a) for a in llm.AGENTS},
        "readiness": llm.readiness(),
        "needs_vision": sorted(llm.NEEDS_VISION),
        "presets": llm.PRESETS,
        "mcp_command": [str(settings.ROOT / ".venv" / "bin" / "factory"), "mcp"],
        "overridden": any(k[0] == "llm" for k in settings.load().overrides),
    }


@router.get("/api/brains")
def get_brains() -> dict[str, Any]:
    return _brains_view()


class BrainsBody(BaseModel):
    providers: list[dict[str, Any]]
    agents: dict[str, str]


@router.put("/api/brains")
def put_brains(body: BrainsBody) -> dict[str, Any]:
    try:
        parsed = [llm._provider_from(p) for p in body.providers]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    ids = [p.id for p in parsed]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "two providers share an id")
    by_id = {p.id: p for p in parsed}
    for agent, chosen in body.agents.items():
        if agent not in llm.AGENTS:
            raise HTTPException(400, f"no agent {agent!r}; have {list(llm.AGENTS)}")
        pid, _, model = chosen.partition("/")
        if pid not in by_id or not model:
            raise HTTPException(400, f"{agent}: choose provider/model, e.g. anthropic/claude-sonnet-5")
        if agent in llm.NEEDS_VISION and not by_id[pid].vision:
            raise HTTPException(400, f"{agent} judges frames; {pid} is marked as unable to see images")
    with db.connect() as conn:
        db.set_override(conn, "llm", "providers", [p.as_dict() for p in parsed])
        db.set_override(conn, "llm", "agents", body.agents)
    settings.invalidate()
    llm._openai_client.cache_clear()
    logs.event("settings.changed", section="llm", key="brains", agents=body.agents, by="human")
    return _brains_view()


class TestBody(BaseModel):
    provider: str
    model: str | None = None


@router.post("/api/brains/test")
def test_brain(body: TestBody) -> dict[str, Any]:
    return llm.test_provider(body.provider, body.model)


@router.get("/api/rules")
def get_rules(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
        latest = db.latest_digest(conn, ch.id)
        text = ch.rules()
    proposals = json.loads(latest["proposals_json"]) if latest else []
    return {
        "channel_id": ch.id,
        # Relative to the repo: the absolute path is long, machine-specific and
        # tells the reader nothing they need.
        "path": str(ch.rules_path.relative_to(settings.ROOT)),
        "text": text,
        "proposals": [p for p in proposals if p not in text],
        "digest": (
            {
                "created_at": latest["created_at"],
                "n_published": latest["n_published"],
                "body": latest["body"],
            }
            if latest
            else None
        ),
    }


class RulesBody(BaseModel):
    channel: str | None = None
    text: str


@router.put("/api/rules")
def put_rules(body: RulesBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        ch.rules()  # make sure the file exists before overwriting it
        ch.rules_path.write_text(body.text)
    return {"path": str(ch.rules_path), "bytes": len(body.text)}


class AcceptBody(BaseModel):
    channel: str | None = None
    rules: list[str]


@router.post("/api/rules/accept")
def accept_rules(body: AcceptBody) -> dict[str, Any]:
    """Append chosen proposals to this channel's rules, one at a time."""
    with db.connect() as conn:
        ch = resolve(conn, body.channel)
        ch.rules()
        try:
            applied = analyst.apply_rules(body.rules, ch.rules_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"applied": applied, "text": ch.rules_path.read_text()}
