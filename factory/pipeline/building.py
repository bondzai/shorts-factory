"""Stages 2-4: render it, name it, judge it.

`render_stage` is the one body that actually renders, measures, hashes and
records — `build`, the agent path and a caption re-render all go through it,
so the three cannot drift apart in what they measure.

`build` resumes: each stage is skipped when its output is already on disk and
still valid, so a build that died after the render does not pay for it twice.
The agent path underneath is the same machine with the judgment left out —
the caller supplies that, and the arithmetic stays here where it cannot be
argued with.
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass

from .. import channels, db, gc, generators, logs, phash, render, settings
from ..agents import metadata as metadata_agent, qc, template
from ..channels import Channel
from ..series import planning as series_planning
from ..models import (
    AWAITING_APPROVAL,
    AWAITING_QC,
    DESCRIBED,
    FAILED,
    PLANNED,
    QC_REJECTED,
    RENDERED,
)
from .common import StageOutcome, qc_enabled, resolve, sample_times
from .spoilers import spoiler


@dataclass
class Written:
    """Metadata already on the row, shaped like the agent's return value."""

    title: str
    description: str
    hashtags: list[str]


def render_stage(conn: sqlite3.Connection, ch: Channel, clip_id: str, params: dict, *, by: str | None = None):
    """Render, measure, hash and record one clip.

    One body for build, the credential-free agent path and a caption re-render,
    so the three cannot drift apart in what they measure.
    """
    try:
        return _render_stage(conn, ch, clip_id, params, by=by)
    except Exception as exc:
        # A season level that cannot be built says why on the level, too
        # (story_unsatisfiable: … is the one the plan has to answer).
        series_planning.mark(conn, ch.id, params, clip_id, series_planning.FAILED, str(exc))
        raise


def _render_stage(conn, ch, clip_id, params, *, by=None):
    row = db.get(conn, clip_id)
    gen = generators.get(row["generator"])
    clip = gen.generate(
        seed=row["seed"], variant=row["variant"], params=params,
        work_dir=settings.load().work_dir / ch.id / clip_id,
    )
    info = render.probe(clip.video_path)
    loudness = render.loudness_lufs(clip.video_path)
    frames = render.sample_frames(clip.video_path, sample_times(info["duration_s"]))
    if not frames:
        raise RuntimeError("could not sample any frame from the render")
    digest_hash = phash.clip_hash(frames)
    sameness = round(
        phash.max_similarity(digest_hash, db.known_phashes(conn, ch.id, exclude=clip_id)), 4
    )
    db.update(
        conn, clip_id, status=RENDERED, video_path=db.relative_video_path(clip.video_path),
        render_desc=clip.description, facts_json=json.dumps(clip.facts, default=str),
        duration_s=info["duration_s"], width=info["width"], height=info["height"],
        fps=info["fps"], loudness_lufs=loudness, phash=digest_hash, sameness=sameness,
        hook_text=clip.facts.get("hook_text"),
        trace_path=db.relative_video_path(clip.trace_path) if clip.trace_path else None,
        level_id=params.get("level_id"),
    )
    series_planning.mark(conn, ch.id, params, clip_id, series_planning.RENDERED)
    # The silent mp4 and the wav are dead the moment the mux lands.
    swept = gc.sweep_intermediates(clip.video_path.parent)
    logs.event(
        "clip.rendered", channel=ch.id, clip=clip_id, duration_s=info["duration_s"],
        loudness_lufs=loudness, sameness=sameness, facts=clip.facts,
        mb_reclaimed=swept.mb, **({"by": by} if by else {}),
    )
    return clip, info, loudness, frames, sameness


def build(conn: sqlite3.Connection, clip_id: str, *, force: bool = False,
          run_qc: bool | None = None) -> StageOutcome:
    """Take a clip as far as the review queue, resuming from wherever it stopped.

    A build that dies after the render but before QC used to leave the clip
    stranded: re-running it would re-render and re-title, paying twice for work
    already on disk. Each stage is skipped when its output is already there and
    still valid, so `resume` is just `build` on a clip that is not `planned`.
    `force` ignores all of that and redoes everything. `run_qc` overrides
    `[qc] enabled`; with QC off the clip stops, made and titled, as awaiting QC.
    """
    row = db.get(conn, clip_id)
    if row is None:
        raise KeyError(f"no clip {clip_id!r}")
    ch = channels.get(conn, row["channel_id"])
    spent = 0.0

    existing = db.video_file(row)
    reuse_render = (
        not force
        and existing is not None
        and existing.exists()
        and row["duration_s"]
        and not row["purged_at"]
    )

    try:
        if reuse_render:
            info = {
                "width": row["width"], "height": row["height"],
                "fps": row["fps"], "duration_s": row["duration_s"],
            }
            loudness = row["loudness_lufs"]
            frames = render.sample_frames(existing, sample_times(info["duration_s"]))
            if not frames:
                raise RuntimeError(f"cannot read frames back from {existing}")
            sameness = row["sameness"] or 0.0
            clip = generators.GeneratedClip(
                video_path=existing,
                duration_s=info["duration_s"],
                description=row["render_desc"] or "",
                facts=json.loads(row["facts_json"] or "{}"),
            )
            logs.event("clip.render_reused", channel=ch.id, clip=clip_id, path=str(existing))
        else:
            if not ch.allows(row["generator"], row["variant"]):
                raise ValueError(
                    f"{ch.id} no longer allows {row['generator']}/{row['variant']}"
                )
            clip, info, loudness, frames, sameness = render_stage(
                conn, ch, clip_id, json.loads(row["params_json"])
            )
    except Exception as exc:
        db.update(conn, clip_id, status=FAILED, reject_reason=f"render: {exc}")
        logs.event(
            "clip.failed", level="error", channel=ch.id, clip=clip_id,
            stage="render", error=str(exc),
        )
        return StageOutcome(clip_id, FAILED, f"render failed: {exc}")

    recent = [r for r in db.recent(conn, ch.id, limit=8) if r["id"] != clip_id]
    reuse_metadata = not force and bool(row["title"]) and bool(row["hashtags_json"])
    try:
        if reuse_metadata:
            meta = Written(
                title=row["title"],
                description=row["description"] or "",
                hashtags=json.loads(row["hashtags_json"]),
            )
            logs.event("clip.metadata_reused", channel=ch.id, clip=clip_id, title=meta.title)
        else:
            meta, cost, by = written_metadata(row, ch, clip, frames, recent, conn=conn)
            spent += cost
            db.update(
                conn,
                clip_id,
                status=DESCRIBED,
                title=meta.title,
                description=meta.description,
                hashtags_json=json.dumps(meta.hashtags),
            )
            logs.event(
                "clip.described", channel=ch.id, clip=clip_id,
                title=meta.title, hashtags=meta.hashtags, cost_usd=round(cost, 6), by=by,
            )
    except Exception as exc:
        db.add_cost(conn, clip_id, spent)
        db.update(conn, clip_id, status=FAILED, reject_reason=f"metadata: {exc}")
        logs.event(
            "clip.failed", level="error", channel=ch.id, clip=clip_id,
            stage="metadata", error=str(exc),
        )
        return StageOutcome(clip_id, FAILED, f"metadata failed: {exc}", spent)

    if not (qc_enabled() if run_qc is None else run_qc):
        db.add_cost(conn, clip_id, spent)
        db.update(conn, clip_id, status=AWAITING_QC, reject_reason=None)
        logs.event("clip.awaiting_qc", channel=ch.id, clip=clip_id, title=meta.title)
        return StageOutcome(clip_id, AWAITING_QC, "made and titled; QC is off — `factory qc` judges it", spent)

    try:
        failures = qc.hard_failures(
            probe=info, loudness_lufs=loudness, sameness=sameness
        )
        verdict, cost = qc.review(
            frames=frames,
            hook=row["hook"] or "",
            description=clip.description,
            recent_descriptions=[r["render_desc"] for r in recent if r["render_desc"]],
        )
        spent += cost
        passed, reason = qc.decide(verdict, failures)
        db.add_cost(conn, clip_id, spent)
        db.update(
            conn,
            clip_id,
            status=AWAITING_APPROVAL if passed else QC_REJECTED,
            qc_json=verdict.model_dump_json(),
            reject_reason=None if passed else reason,
        )
        logs.event(
            "clip.qc", level="info" if passed else "warn",
            channel=ch.id, clip=clip_id, passed=passed,
            hook_strength=verdict.hook_strength, policy_risk=verdict.policy_risk,
            looks_templated=verdict.looks_templated,
            hard_failures=failures, reason=reason or None,
        )
        detail = meta.title if passed else reason
        return StageOutcome(
            clip_id, AWAITING_APPROVAL if passed else QC_REJECTED, detail, spent
        )
    except Exception as exc:
        db.add_cost(conn, clip_id, spent)
        db.update(conn, clip_id, status=FAILED, reject_reason=f"qc: {exc}")
        logs.event(
            "clip.failed", level="error", channel=ch.id, clip=clip_id,
            stage="qc", error=str(exc),
        )
        return StageOutcome(clip_id, FAILED, f"qc failed: {exc}", spent)


def written_metadata(row, ch, clip, frames, recent, *, conn: sqlite3.Connection | None = None):
    """The clip's words, from the template or the Metadata agent, per
    `[llm] metadata_source`. Returns (metadata, cost, who).

    The template writes only what the rules already fix and is held to the
    same spoiler check as an agent — a template with a bug in it must not be
    the one thing that can ship a result in a title. What it cannot write
    (another generator's clip) goes to the agent, and the log says so.

    A season level clip is the exception: its words come from the series
    copy stage (`[series] copy_source`), which asks the copy brain, checks
    every candidate and falls back to the template per field. Its hook is
    recorded, not burned — that is `factory copy --burn-hook`.
    """
    if (copied := _level_copy(conn, row, ch, clip)) is not None:
        return copied
    source = settings.load().llm.get("metadata_source", "agent")
    if source == "template" and template.can_write(clip.facts):
        meta, cost = template.write_metadata(facts=clip.facts, seed=row["seed"],
                                             taken={r["title"] for r in recent if r["title"]})
        first_sentence = meta.description.split(". ")[0]
        problem = spoiler(clip.facts, title=meta.title, comment_prompt=meta.comment_prompt,
                          description=first_sentence)
        if problem:
            raise ValueError(f"template: {problem}")
        return meta, cost, "template"
    if source == "template":
        logs.event("clip.metadata_template_declined", channel=ch.id, clip=row["id"],
                   variant=clip.facts.get("variant"))
    meta, cost = metadata_agent.write_metadata(
        description=clip.description,
        facts=clip.facts,
        hook=row["hook"] or "",
        rules=ch.rules(),
        recent_titles=[r["title"] for r in recent if r["title"]],
        frames=frames,
    )
    return meta, cost, "agent"


def _level_copy(conn, row, ch, clip):
    """(metadata, cost, who) for a level clip, or None for any other clip.
    level_id is read now: the row the caller holds may predate the render.
    Without a connection only the row's own level_id is known, and a clip
    that has none never opens the database here."""
    own = conn is None
    if own:
        if "level_id" not in row.keys() or not row["level_id"]:
            return None
        conn = db.connect()
    try:
        fresh = db.get(conn, row["id"])
        if fresh is None or not fresh["level_id"]:
            return None
        from ..series import copywriter

        result = copywriter.write(conn, row["id"], facts=clip.facts, rules=ch.rules())
        copywriter.record(conn, result)
        return result.metadata, result.cost, f"copy/{result.source}"
    finally:
        if own:
            conn.close()


def run_qc(conn: sqlite3.Connection, channel: Channel | str | None, *,
           clip_ids: list[str] | None = None, limit: int = 50) -> list[StageOutcome]:
    """Judge clips that were made while QC was off. Nothing is re-rendered or
    re-titled: build resumes each one at the QC stage."""
    from .. import llm

    ready = llm.readiness(agents=["qc"]).get("qc", {})
    if not ready.get("ok"):
        raise ValueError(f"the QC brain is not ready: {ready.get('why')}")
    ch = resolve(conn, channel)
    rows = db.by_status(conn, ch.id, AWAITING_QC, limit)
    if clip_ids:
        rows = [r for r in rows if r["id"] in set(clip_ids)]
    outcomes = []
    for row in rows:
        outcome = build(conn, row["id"], run_qc=True)
        if outcome.status == FAILED and outcome.detail.startswith("qc failed"):
            # The brain erred (down, context too small, bad JSON): that is not
            # a verdict on the clip, so it goes back to wait for the next run.
            db.update(conn, row["id"], status=AWAITING_QC, reject_reason=outcome.detail[:300])
            outcome = StageOutcome(row["id"], AWAITING_QC, outcome.detail, outcome.cost_usd)
        outcomes.append(outcome)
    return outcomes


def build_all(
    conn: sqlite3.Connection, channel: Channel | str | None, limit: int = 20
) -> list[StageOutcome]:
    ch = resolve(conn, channel)
    return [build(conn, row["id"]) for row in db.by_status(conn, ch.id, PLANNED, limit)]


def create_and_render(
    conn: sqlite3.Connection,
    channel: Channel | str | None,
    *,
    variant: str,
    generator: str = "physics",
    seed: int | None = None,
    hook: str = "",
    why: str = "",
    params: dict | None = None,
) -> tuple[str, list[bytes], dict]:
    """Render one clip with no model involved. Returns (clip_id, frames, facts)."""
    params = params or {}

    ch = resolve(conn, channel)
    if not ch.allows(generator, variant):
        raise ValueError(
            f"{ch.id} does not allow {generator}/{variant}; "
            f"allowed: {ch.variants or 'any ready module'}"
        )
    # A seed the caller named is used as named. This used to re-roll any seed
    # a clip had ever carried, so a task that said "seed 7301" — a seed that
    # sat in the bin — rendered a random race three times running and
    # reported it done; the sameness gate is what guards against repeats,
    # not this. Only an unnamed seed avoids the ones already taken.
    if seed is None:
        used = {r["seed"] for r in conn.execute("SELECT seed FROM clips").fetchall()}
        rng = random.Random()
        while seed is None or seed in used:
            seed = rng.randrange(2**31 - 1)

    clip_id = db.insert_clip(
        conn, channel_id=ch.id, generator=generator, variant=variant, seed=seed,
        params=params, hook=hook, plan_why=why or "created by an external agent",
    )
    logs.event(
        "clip.planned", channel=ch.id, clip=clip_id, generator=generator,
        variant=variant, seed=seed, hook=hook, by="agent",
    )

    clip, info, loudness, frames, sameness = render_stage(conn, ch, clip_id, params, by="agent")
    facts = {
        **info,
        "loudness_lufs": loudness,
        "sameness": sameness,
        "shows": clip.description,
        # Without this an external agent is asked whether the clip repeats the
        # channel and given nothing to compare it against, so it answers about
        # the format in general instead. Our own QC agent always got this.
        "recent_on_this_channel": [
            {"title": r["title"], "shows": r["render_desc"]}
            for r in db.recent(conn, ch.id, limit=6)
            if r["id"] != clip_id and r["render_desc"]
        ],
        "generator_facts": clip.facts,
        # Measured here, reported so the caller can see what it is judged against.
        "hard_failures": qc.hard_failures(
            probe=info, loudness_lufs=loudness, sameness=sameness
        ),
    }
    return clip_id, frames, facts
