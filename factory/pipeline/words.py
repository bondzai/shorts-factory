"""The words on a clip, after it exists: its metadata, its description, the
caption burnt into the opening frames, and the title of a published one.

All four go through the spoiler gate, and a caption change goes through the
renderer again — a re-render is a re-render, so the hard gates re-run.
"""

from __future__ import annotations

import json
import re
import sqlite3

from .. import channels, db, logs, playbooks, settings
from .. import publish as drivers
from ..models import (
    APPROVED,
    AWAITING_APPROVAL,
    DESCRIBED,
    FAILED,
    PLANNED,
    PUBLISHED,
    QC_REJECTED,
    RENDERED,
    TITLE_MAX,
    TITLE_MIN,
    Metadata,
)
from ..agents import qc, titles as title_agent
from ..generators import physics
from ..series import standings
from . import building
from .common import StageOutcome
from .spoilers import spoiler


def attach_metadata(conn: sqlite3.Connection, clip_id: str, meta) -> None:
    """Store a title written by the caller. Validated exactly as the agent's is."""
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    facts = json.loads(row["facts_json"] or "{}")
    first_sentence = re.split(r"(?<=[.!?])\s", meta.description.strip(), 1)[0]
    problem = spoiler(facts, title=meta.title, hook_text=meta.hook_text,
                      comment_prompt=meta.comment_prompt, description=first_sentence)
    if problem:
        raise ValueError(problem)
    db.update(
        conn, clip_id, status=DESCRIBED, title=meta.title,
        description=meta.description, hashtags_json=json.dumps(meta.hashtags),
        comment_prompt=(meta.comment_prompt or "").strip() or None,
    )
    logs.event(
        "clip.described", channel=row["channel_id"], clip=clip_id,
        title=meta.title, hashtags=meta.hashtags, cost_usd=0.0, by="agent",
        comment_prompt=meta.comment_prompt,
    )
    wanted = (meta.hook_text or "").strip()
    if wanted and wanted != (row["hook_text"] or ""):
        rehook(conn, clip_id, wanted, by="agent")


def redescribe(conn: sqlite3.Connection, clip_id: str, description: str, *, by: str = "human") -> str:
    """Change a description. Held to the same bounds as an agent's, and its
    first sentence to the same spoiler gate as a title, because it is the
    sentence the feed shows under the title."""
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    description = description.strip()
    lo, hi = Metadata.model_fields["description"].metadata[0].min_length, Metadata.model_fields["description"].metadata[1].max_length
    if not lo <= len(description) <= hi:
        raise ValueError(f"description must be {lo}-{hi} characters")
    first_sentence = re.split(r"(?<=[.!?])\s", description, 1)[0]
    problem = spoiler(json.loads(row["facts_json"] or "{}"), description=first_sentence)
    if problem:
        raise ValueError(problem)
    db.update(conn, clip_id, description=description)
    logs.event("clip.redescribed", channel=row["channel_id"], clip=clip_id, by=by)
    return description


def rehook(conn: sqlite3.Connection, clip_id: str, text: str | None, *, by: str = "human",
           background: str | None = None) -> StageOutcome:
    """Burn a different opening caption into a clip that has not shipped.

    Same seed, same race: the simulation is deterministic, so the only pixels
    that change are the caption's. The hard gates still re-run, because a
    re-render is a re-render. A clip in the review queue stays there; an
    approved one goes back to the queue, since what was approved has changed.
    """
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    if row["status"] == PUBLISHED:
        raise ValueError(f"{clip_id} is published; the caption is in the uploaded pixels")
    ch = channels.get(conn, row["channel_id"])
    params = json.loads(row["params_json"] or "{}")
    # Pin the stages the clip was actually raced on. A stage chosen by the
    # seed is a weighted pick from the registry, and the registry grows: the
    # same seed re-rendered after new stages arrive would race elsewhere and
    # the caption would land on a different clip.
    facts = json.loads(row["facts_json"] or "{}")
    raced = [r.get("stage") for r in facts.get("rounds") or [] if r.get("stage")]
    if row["generator"] == "physics" and raced:
        params.setdefault("stage", raced[0])
        if len(raced) > 1:
            params.setdefault("final_stage", raced[1])
    if text is None:
        # Let the render choose from what it measures — for a clip rendered
        # before captions were measured, this is how it catches up.
        params.pop("hook_text", None)
    else:
        text = text.strip()
        if not text:
            raise ValueError("an empty caption is not a caption; pass None to let the render choose")
        params["hook_text"] = text
    if background is not None:
        if background.strip():
            physics.parse_hex(background)
            params["background"] = background.strip()
        else:
            params.pop("background", None)  # back to the theme's palette
    db.update(conn, clip_id, params_json=json.dumps(params))
    before = row["status"]
    try:
        clip, info, loudness, frames, sameness = building.render_stage(conn, ch, clip_id, params, by=by)
    except Exception as exc:
        db.update(conn, clip_id, status=FAILED, reject_reason=f"render: {exc}")
        standings.sync(conn, clip_id)
        logs.event("clip.failed", level="error", channel=ch.id, clip=clip_id, stage="rehook", error=str(exc))
        return StageOutcome(clip_id, FAILED, f"render failed: {exc}")
    failures = qc.hard_failures(probe=info, loudness_lufs=loudness, sameness=sameness)
    if failures:
        reason = "; ".join(failures)
        db.update(conn, clip_id, status=QC_REJECTED, reject_reason=reason)
        standings.sync(conn, clip_id)
        logs.event("clip.qc", level="warn", channel=ch.id, clip=clip_id, passed=False, hard_failures=failures, by=by)
        return StageOutcome(clip_id, QC_REJECTED, reason)
    # The person re-captioning an approved clip is the person who approved it,
    # so it stays approved. An agent's change is a change someone should see.
    if before == APPROVED:
        after = APPROVED if by == "human" else AWAITING_APPROVAL
    elif before in (PLANNED, RENDERED, FAILED, QC_REJECTED):
        after = RENDERED
    else:
        after = before
    db.update(conn, clip_id, status=after)
    standings.sync(conn, clip_id)  # an agent's rehook un-approves; the table follows
    shown = clip.facts.get("hook_text")
    logs.event("clip.rehooked", channel=ch.id, clip=clip_id, hook_text=shown, was=before, now=after, by=by,
               measured=text is None)
    return StageOutcome(clip_id, after, f"caption is now {shown!r}")


def retitle(
    conn: sqlite3.Connection, clip_id: str, title: str, *, by: str = "human", why: str = ""
) -> dict:
    """Change a title and keep what it replaced, with the numbers at that moment.

    Retitling is the one lever left on a published clip, and without a snapshot
    it is a lever with no gauge: next week's metrics would be credited to a
    title that was only on the video for half the period.
    """
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    if not row["title"]:
        raise ValueError(f"{clip_id} has no title yet; write metadata first")
    title = " ".join(title.split())
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        raise ValueError(f"title must be {TITLE_MIN}-{TITLE_MAX} characters, like every title here")
    if title == row["title"]:
        raise ValueError("that is already the title")
    problem = spoiler(json.loads(row["facts_json"] or "{}"), title=title)
    if problem:
        raise ValueError(problem)
    history = json.loads(row["title_history_json"] or "[]")
    history.append({
        "title": row["title"], "until": db.now(), "by": by, "why": why,
        "views": row["views"], "avg_view_pct": row["avg_view_pct"],
        "swipe_away_pct": row["swipe_away_pct"], "metrics_at": row["metrics_at"],
    })
    db.update(conn, clip_id, title=title, title_history_json=json.dumps(history))
    ch = channels.get(conn, row["channel_id"])
    # Status, not the timestamp: a clip can be stamped and then thrown out, and
    # a thrown-out clip is not on anyone's screen.
    published = row["status"] == PUBLISHED
    logs.event(
        "clip.retitled", channel=ch.id, clip=clip_id, title=title, was=row["title"],
        by=by, why=why, published=published,
    )
    pushed, push_error = False, None
    if published and row["remote_id"]:
        # A driver that can reach the video changes it there too, so the gauge
        # this function keeps (what each title earned) matches what viewers saw.
        driver = drivers.get(ch.driver, ch)
        if hasattr(driver, "update_metadata"):
            try:
                pushed = bool(driver.update_metadata(row["remote_id"], title=title))
            except Exception as exc:
                push_error = str(exc)[:200]
                logs.event("clip.retitle_push_failed", level="warn", channel=ch.id,
                           clip=clip_id, error=push_error)
    return {
        "clip": clip_id, "title": title, "was": row["title"], "published": published,
        "changes": len(history), "pushed": pushed, "push_error": push_error,
        # Nothing reaches YouTube by itself on a manual channel, or when the
        # push failed.
        "needs_manual_update": published and not pushed,
    }


# --- title ideas ---------------------------------------------------------------

EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
FEED_MAX = 45  # what a phone shows of a title in the Shorts feed before it is cut
SHAPE_WORDS = 3  # a title that opens on the same three words is the same title


def shape(title: str) -> str:
    """The opening of a title, as the feed reads it: the first three words,
    lowercased, punctuation gone. Two titles with the same shape are the
    same ask in different colours, which is what an operator pressing the
    button is trying to get away from."""
    words = re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
    return " ".join(words[:SHAPE_WORDS])


def title_ideas(conn: sqlite3.Connection, clip_id: str, *, captions: bool = False) -> dict:
    """Five ways to ask for the pick, one per angle, from the Metadata brain
    — then the server decides which the operator gets to see.

    Nothing the model says is trusted. Each idea goes through the same
    spoiler gate as a title an agent submits, the feed's 60-character line,
    the channel's emoji setting, English only, and a repetition check
    against the last twenty titles on the channel by their opening three
    words. What was dropped is reported with its reason, so a button that
    comes back with two ideas instead of five says why.
    """
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    facts = json.loads(row["facts_json"] or "{}")
    recent = [r["title"] for r in db.recent(conn, row["channel_id"], limit=20) if r["title"] and r["id"] != clip_id]
    emoji_ok = bool(settings.load().raw.get("titles", {}).get("emoji", False))
    ideas, cost = title_agent.suggest(
        facts=facts, recent_titles=recent, directions=playbooks.directions_text(conn, row["channel_id"]),
        emoji_allowed=emoji_ok, want_captions=captions and row["status"] != PUBLISHED,
    )
    taken = {shape(t) for t in recent} | {shape(row["title"] or "")}
    kept, dropped = [], []
    for idea in ideas.ideas:
        title = " ".join(idea.title.split())
        why = None
        if not TITLE_MIN <= len(title) <= FEED_MAX:
            why = f"{len(title)} characters; the feed shows {FEED_MAX} and the floor is {TITLE_MIN}"
        elif not emoji_ok and EMOJI.search(title):
            why = "emoji, and the channel's titles setting says none"
        elif not EMOJI.sub("", title).isascii():  # an allowed emoji is not Thai
            why = "not plain English"
        elif shape(title) in taken:
            why = f"opens like a title already used ({shape(title)!r})"
        else:
            why = spoiler(facts, title=title, hook_text=idea.caption)
        if why:
            dropped.append({"angle": idea.angle, "title": title, "why": why})
            continue
        taken.add(shape(title))
        kept.append({"angle": idea.angle, "title": title, "caption": idea.caption, "why": idea.why})
    logs.event("clip.title_ideas", channel=row["channel_id"], clip=clip_id, kept=len(kept),
               dropped=len(dropped), cost_usd=round(cost, 6))
    return {"clip": clip_id, "ideas": kept, "dropped": dropped, "cost_usd": round(cost, 6)}
