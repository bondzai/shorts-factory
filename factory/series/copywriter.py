"""Copy for a level clip: gather what is known, ask the brain, check, fall back.

docs/08 §4 "Copy". The brain sees the race without its result; its
candidates go through `copy_check`; any field with nothing passing takes the
template's words, filled with the standings. The description is assembled by
code: line 1 (chosen), the standings before this race in words, the season's
footer. Which path each field took is recorded in `facts["copy"]`.

Nothing here burns pixels: the chosen hook is recorded, and only
`factory copy --burn-hook` sends it through `rehook`.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .. import db, llm, logs, settings
from ..agents import template
from ..models import Metadata
from . import cast as cast_mod
from . import copy_check
from . import season as season_mod
from .copy_check import FIELDS, RECENT, Chosen, CopyContext, PlaceholderError, check, fill
from .outcome import Outcome

#: Keys of the render's facts that carry the result; the brain never sees them.
HIDDEN_FACTS = {"winner", "finishes", "runner_up", "outcome", "placements", "copy", "copy_source",
                "winner_frame", "order", "ranking"}
PIN_ENDINGS = ("who's your pick?", "which one are you backing?", "call it before it starts.",
               "pick one before the first bend.")
OPENER = "Season opener — everyone starts at zero."
NO_RESULTS = "No points on the board yet."


@dataclass
class Setting:
    """Everything gathered about one level clip."""

    clip_id: str
    channel_id: str
    level_id: str
    season_id: str | None
    seed: int
    facts: dict[str, Any]
    ctx: CopyContext
    season: season_mod.Season | None = None
    level: season_mod.Level | None = None
    cast: cast_mod.Cast | None = None
    outcome: Outcome | None = None
    table: list[dict[str, Any]] | None = None  # None: standings unavailable
    recent_hooks: list[str] = field(default_factory=list)


@dataclass
class Result:
    metadata: Metadata
    chosen: Chosen
    fallback: dict[str, str | None]
    source: str  # local | template | mixed | agent
    cost: float
    setting: Setting

    def record(self) -> dict[str, Any]:
        return {"source": dict(self.chosen.source), "hook": self.chosen.text.get("hook"),
                "rejected": list(self.chosen.rejected)}


# --- gathering ---------------------------------------------------------------------

def _season_of(conn: sqlite3.Connection, channel_id: str, level_id: str, clip_id: str) -> str | None:
    rows = conn.execute(
        "SELECT season_id, clip_id FROM levels WHERE channel_id = ? AND id = ?", (channel_id, level_id)
    ).fetchall()
    for r in rows:
        if r["clip_id"] == clip_id:
            return r["season_id"]
    if len(rows) == 1:
        return rows[0]["season_id"]
    have = season_mod.seasons(channel_id)
    return have[0] if len(have) == 1 else None


def _standings(conn, channel_id, season_id, level_id):
    """(table, h2h) before this level, or (None, None) when there is no
    standings module or it fails — copy then goes without standings."""
    if not season_id:
        return None, None
    try:
        standings = importlib.import_module("factory.series.standings")
        table = standings.table(conn, channel_id, season_id, before_level=level_id)
    except Exception as exc:
        logs.event("copy.no_standings", level="warn", channel=channel_id, level_id=level_id, error=str(exc)[:200])
        return None, None
    cache: dict[tuple[str, str], tuple[int, int]] = {}

    def h2h(a: str, b: str) -> tuple[int, int]:
        if (a, b) not in cache:
            cache[(a, b)] = tuple(standings.h2h(conn, channel_id, season_id, a, b, before_level=level_id))
        return cache[(a, b)]

    return list(table), h2h


def leader(table: list[dict[str, Any]] | None) -> str | None:
    """The one name on top before this race; None at zero or on a tie."""
    if not table:
        return None
    top = max(int(r.get("points") or 0) for r in table)
    at_top = [r for r in table if int(r.get("points") or 0) == top]
    return at_top[0].get("name") if top > 0 and len(at_top) == 1 else None


def gather(conn: sqlite3.Connection, clip_id: str, facts: dict[str, Any] | None = None) -> Setting:
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    level_id = row["level_id"]
    if not level_id:
        raise ValueError(f"{clip_id} is not a season level clip")
    channel_id = row["channel_id"]
    facts = facts if facts is not None else json.loads(row["facts_json"] or "{}")
    season_id = _season_of(conn, channel_id, level_id, clip_id)
    season = level = cst = None
    try:
        if season_id or season_mod.seasons(channel_id):
            season = season_mod.load(channel_id, season_id)
            season_id = season.id
            level = season.level(level_id)
    except Exception as exc:
        logs.event("copy.no_season", level="warn", channel=channel_id, clip=clip_id, error=str(exc)[:200])
    try:
        cst = cast_mod.load(channel_id)
    except Exception as exc:
        logs.event("copy.no_cast", level="warn", channel=channel_id, clip=clip_id, error=str(exc)[:200])

    screen = list(facts.get("cast") or (level.entrants if level else []) or facts.get("lineup") or [])

    def name_of(eid: str) -> str:
        if cst:
            try:
                return cst.get(eid).name
            except KeyError:
                pass
        return eid

    entrants = [(eid, name_of(eid)) for eid in screen]
    outcome = None
    if facts.get("outcome"):
        try:
            outcome = Outcome.model_validate(facts["outcome"])
        except Exception:
            outcome = None
    from ..pipeline.spoilers import winners as fact_winners

    won = set(fact_winners(facts))
    if outcome:
        for p in outcome.placements:
            if p.rank == 1:
                won |= {p.entrant_id, name_of(p.entrant_id)}

    table, h2h = _standings(conn, channel_id, season_id, level_id)
    recent = [r for r in db.recent(conn, channel_id, limit=RECENT + 1) if r["id"] != clip_id][:RECENT]
    ctx = CopyContext(
        entrants=entrants,
        values={
            "margin_s": outcome.margin_s if outcome else facts.get("margin_s"),
            "lead_changes": outcome.lead_changes if outcome else None,
            "entrant_count": len(entrants) or None,
            "leader_name": leader(table),
        },
        standings=None if table is None else {r["entrant_id"]: int(r.get("points") or 0) for r in table},
        h2h=h2h,
        known_ids=set(screen) | (set(cst.ids()) if cst else set()) | {r["entrant_id"] for r in table or []},
        facts=facts,
        winners=won,
        recent_titles=[r["title"] for r in recent if r["title"]],
        recent_pins=[r["comment_prompt"] for r in recent if r["comment_prompt"]],
        keywords=list(season.keywords) if season else [],
        emoji_ok=bool(settings.load().raw.get("titles", {}).get("emoji", False)),
    )
    return Setting(
        clip_id=clip_id, channel_id=channel_id, level_id=level_id, season_id=season_id,
        seed=int(row["seed"] or 0), facts=facts, ctx=ctx, season=season, level=level, cast=cst,
        outcome=outcome, table=table, recent_hooks=[r["hook_text"] for r in recent if r["hook_text"]],
    )


# --- what the brain (or an outside agent) is shown ------------------------------

def scrub(facts: dict[str, Any]) -> dict[str, Any]:
    """The render's facts with every trace of the result removed."""
    out = {k: v for k, v in facts.items() if k not in HIDDEN_FACTS}
    if isinstance(out.get("rounds"), list):
        out["rounds"] = [{k: v for k, v in r.items() if k not in HIDDEN_FACTS} if isinstance(r, dict) else r
                         for r in out["rounds"]]
    return out


def inputs(s: Setting, rules: str) -> dict[str, Any]:
    hints = s.level.copy_.model_dump(exclude_none=True) if s.level else {}
    bios = {}
    if s.cast:
        for eid, _ in s.ctx.entrants:
            try:
                bios[eid] = s.cast.get(eid).bio
            except KeyError:
                pass
    return {
        "episode": {
            "season": s.season.title if s.season else s.season_id,
            "level": s.level_id,
            "world": s.level.world if s.level else None,
            "format": s.level.format if s.level else None,
            "stage": template.stage_of(s.facts),
            "stage_words": s.facts.get("stage_words"),
        },
        "race_without_result": s.outcome.without_winner() if s.outcome else None,
        "facts": scrub(s.facts),
        "entrants_in_screen_order": [{"id": eid, "name": n, "bio": bios.get(eid, "")} for eid, n in s.ctx.entrants],
        "standings_before_this_race": s.table,
        "plan_hints": hints,
        "channel_rules": rules,
        "recent": {"titles": s.ctx.recent_titles, "hooks": s.recent_hooks, "pins": s.ctx.recent_pins},
        "placeholders": copy_check.PLACEHOLDERS,
        "allowed_placeholders": {f: sorted(copy_check.ALLOWED[f]) for f in FIELDS},
        "keywords_preferred_in_first_three_title_words": s.ctx.keywords,
    }


# --- the template's words ---------------------------------------------------------

def _first_passing(field_: str, options: list[str], ctx: CopyContext, rejected: list[dict]) -> str | None:
    """The first option that passes, filled; else the first one anyway (the
    template is the last resort) with why it fell short recorded — unless it
    gives the race away, which nothing is allowed to."""
    options = list(dict.fromkeys(o for o in options if o))
    reasons = []
    for o in options:
        why = check(field_, o, ctx)
        if why is None:
            return fill(o, ctx, field_)
        reasons.append(why)
    if not options:
        return None
    try:
        text = fill(options[0], ctx, field_)
    except PlaceholderError as exc:
        raise ValueError(f"template {field_}: {exc}") from None
    if problem := copy_check._spoiler(field_, text, ctx):
        raise ValueError(f"template {field_}: {problem}")
    rejected.append({"field": field_, "text": options[0], "why": f"template used anyway: {reasons[0]}"})
    return text


def fallback(s: Setting) -> tuple[dict[str, str | None], list[dict[str, str]]]:
    """Per field, the template's words for this level."""
    rejected: list[dict[str, str]] = []
    names = [n for _, n in s.ctx.entrants] or list(s.facts.get("lineup") or [])
    tfacts = {**s.facts, "lineup": names}
    out: dict[str, str | None] = {}
    shapes = [template.title(tfacts, s.seed + k) for k in range(len(template.SHAPES))] if names else []
    out["title"] = _first_passing("title", shapes, s.ctx, rejected)
    out["hook"] = None  # the render's own caption stays
    lineup = template.names(names) if names else ""
    pins = [f"{lineup} — {end}" for end in PIN_ENDINGS] if names else []
    out["pin"] = _first_passing("pin", pins, s.ctx, rejected)
    words = s.facts.get("stage_words") or f"the {template.stage_of(s.facts)}"
    lines = [f"{{entrant_count}} marbles race down {words}.",
             f"{{entrant_count}} marbles race down the {template.stage_of(s.facts)}."]
    out["desc_line1"] = _first_passing("desc_line1", lines, s.ctx, rejected)
    return out, rejected


def standings_line(s: Setting) -> str | None:
    """The table before this race, in words, filled from placeholders."""
    if s.table is None:
        return None
    if not s.table or all(int(r.get("points") or 0) == 0 for r in s.table):
        # Standings are read when the clip is rendered, so a level rendered
        # before the one ahead of it is approved sees an empty table too.
        # Only the season's first level is the opener.
        first = s.season is not None and s.season.levels and s.season.levels[0].id == s.level_id
        return OPENER if first else NO_RESULTS
    rows = sorted(s.table, key=lambda r: -int(r.get("points") or 0))
    raw = "Standings: " + ", ".join(f"{r['name']} {{standing:{r['entrant_id']}}}" for r in rows) + "."
    return fill(raw, s.ctx, "description")


def description(s: Setting, line1: str | None, rejected: list[dict[str, str]] | None = None) -> str:
    lines = [line1] if line1 else []
    if (st := standings_line(s)) is not None:
        lines.append(st)
    if s.season and s.season.footer:
        try:
            lines.append(fill(s.season.footer.strip(), s.ctx, "description"))
        except PlaceholderError as exc:
            if rejected is not None:
                rejected.append({"field": "footer", "text": s.season.footer, "why": str(exc)})
    return "\n".join(lines)[:900]


# --- writing ------------------------------------------------------------------------

def overall(source: dict[str, str]) -> str:
    kinds = set(source.values())
    return kinds.pop() if len(kinds) == 1 else "mixed"


def compose(s: Setting, chosen: Chosen, fb: dict[str, str | None], cost: float = 0.0) -> Result:
    desc = description(s, chosen.text.get("desc_line1"), chosen.rejected)
    source = overall(chosen.source)
    meta = Metadata(
        title=chosen.text["title"], description=desc, hashtags=list(template.HASHTAGS),
        rationale=f"Season copy ({source}): checked against the level's facts and standings.",
        hook_text=None,  # burned only through rehook
        comment_prompt=chosen.text.get("pin"),
    )
    return Result(metadata=meta, chosen=chosen, fallback=fb, source=source, cost=cost, setting=s)


def write(conn: sqlite3.Connection, clip_id: str, *, facts: dict[str, Any] | None = None,
          brain: str | None = None, rules: str = "") -> Result:
    """Copy for a level clip. `brain` is "local" or "template"; default
    `[series] copy_source`. The brain is skipped when it is not ready."""
    s = gather(conn, clip_id, facts)
    fb, fb_rejected = fallback(s)
    brain = brain or settings.load().raw.get("series", {}).get("copy_source", "local")
    if brain not in ("local", "template"):
        raise ValueError(f"copy brain must be local or template, not {brain!r}")
    proposal, cost, notes = None, 0.0, []
    if brain == "local":
        try:
            ready = llm.readiness(("copy",)).get("copy", {})
        except Exception as exc:
            ready = {"ok": False, "why": str(exc)}
        if ready.get("ok"):
            from ..agents import copy as copy_agent

            try:
                proposal, cost = copy_agent.propose(**inputs(s, rules))
            except Exception as exc:
                notes.append({"field": "*", "text": "", "why": f"brain failed: {str(exc)[:200]}"})
        else:
            notes.append({"field": "*", "text": "", "why": f"brain not ready: {ready.get('why')}"})
    chosen = copy_check.choose(proposal, s.ctx, fb)
    chosen.rejected = notes + chosen.rejected + fb_rejected
    return compose(s, chosen, fb, cost)


def record(conn: sqlite3.Connection, result: Result, *, by: str = "pipeline") -> None:
    """Store which path each field took, and the pin; log it."""
    s = result.setting
    row = db.get(conn, s.clip_id)
    facts = json.loads(row["facts_json"] or "{}")
    facts["copy"] = result.record()
    facts["copy_source"] = result.source
    s.facts["copy"], s.facts["copy_source"] = facts["copy"], facts["copy_source"]
    db.update(conn, s.clip_id, facts_json=json.dumps(facts, default=str),
              comment_prompt=(result.metadata.comment_prompt or "").strip() or None)
    logs.event("copy.chosen", channel=s.channel_id, clip=s.clip_id, level_id=s.level_id,
               source=result.source, fields=result.chosen.source, rejected=len(result.chosen.rejected),
               cost_usd=round(result.cost, 6), by=by)


def apply(conn: sqlite3.Connection, result: Result, *, by: str = "human") -> dict[str, Any]:
    """Put copy on an existing clip: the title through `retitle` (its history
    kept), the description through `redescribe`, the pin, and the record."""
    from ..pipeline import words

    s = result.setting
    row = db.get(conn, s.clip_id)
    meta = result.metadata
    changed = []
    if not row["title"]:
        db.update(conn, s.clip_id, title=meta.title, hashtags_json=json.dumps(meta.hashtags))
        changed.append("title")
    elif row["title"] != meta.title:
        words.retitle(conn, s.clip_id, meta.title, by=by, why=f"copy ({result.source})")
        changed.append("title")
    if (row["description"] or "") != meta.description:
        words.redescribe(conn, s.clip_id, meta.description, by=by)
        changed.append("description")
    if (row["comment_prompt"] or "") != (meta.comment_prompt or ""):
        changed.append("pin")
    record(conn, result, by=by)
    return {"clip": s.clip_id, "changed": changed, "source": result.source,
            "title": meta.title, "pin": meta.comment_prompt, "hook": result.chosen.text.get("hook")}


def submit(conn: sqlite3.Connection, clip_id: str, texts: dict[str, str | None], *, by: str = "agent") -> dict[str, Any]:
    """An outside agent's copy, through the same validator. Every field must
    pass or nothing is applied. An empty hook keeps the render's caption."""
    s = gather(conn, clip_id)
    fb, fb_rejected = fallback(s)
    reasons = []
    chosen = Chosen()
    for f in FIELDS:
        text = " ".join((texts.get(f) or "").split())
        if f == "hook" and not text:
            chosen.text[f], chosen.source[f] = None, "template"
            continue
        why = check(f, text, s.ctx)
        if why:
            reasons.append({"field": f, "text": text, "why": why})
        else:
            chosen.text[f], chosen.source[f] = fill(text, s.ctx, f), by
    if reasons:
        return {"clip": clip_id, "applied": False, "rejected": reasons}
    chosen.rejected = fb_rejected
    out = apply(conn, compose(s, chosen, fb), by=by)
    return {**out, "applied": True}
