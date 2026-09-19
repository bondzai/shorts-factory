"""The shared pipe. Every generator's output walks these stages in this order.

    plan -> render -> metadata -> qc -> (queue) -> approve -> publish -> metrics

Every stage is scoped to one channel: its rules, its allowed generators, its
publish driver, its credentials, its sameness history. Nothing crosses.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import channels, db, gc, generators, logs, phash, publish, render, settings
from .agents import analyst, idea, metadata as metadata_agent, qc
from .channels import Channel
from .models import (
    APPROVED,
    AWAITING_APPROVAL,
    DESCRIBED,
    FAILED,
    PLANNED,
    PUBLISHED,
    QC_REJECTED,
    RENDERED,
)


@dataclass
class _Written:
    """Metadata already on the row, shaped like the agent's return value."""

    title: str
    description: str
    hashtags: list[str]


@dataclass
class StageOutcome:
    clip_id: str
    status: str
    detail: str
    cost_usd: float = 0.0


def _sample_times(duration: float) -> list[float]:
    return [
        min(0.3, duration / 10),
        duration * 0.35,
        duration * 0.7,
        max(0.0, duration - 0.35),
    ]


def resolve(conn: sqlite3.Connection, channel: Channel | str | None) -> Channel:
    if isinstance(channel, Channel):
        return channel
    return channels.resolve(conn, channel)


# --- stage 1: plan -----------------------------------------------------------

def plan(
    conn: sqlite3.Connection, channel: Channel | str | None, count: int
) -> tuple[list[str], float]:
    ch = resolve(conn, channel)
    recent = db.recent(conn, ch.id, limit=12)
    used = {row["seed"] for row in conn.execute("SELECT seed FROM clips").fetchall()}
    plans, cost = idea.propose(
        count=count,
        rules=ch.rules(),
        recent=recent,
        used_seeds=used,
        channel_name=ch.name,
        allowed=ch.variants,
    )
    ids = []
    for item in plans:
        ids.append(
            db.insert_clip(
                conn,
                channel_id=ch.id,
                generator=item.generator,
                variant=item.variant,
                seed=item.seed,
                params=item.params,
                hook=item.hook,
                plan_why=item.why,
            )
        )
    if ids:
        db.add_cost(conn, ids[0], cost)  # one call covered the whole batch
    for clip_id, item in zip(ids, plans):
        logs.event(
            "clip.planned", channel=ch.id, clip=clip_id,
            generator=item.generator, variant=item.variant, seed=item.seed,
            hook=item.hook,
        )
    return ids, cost


# --- stages 2-4: render, metadata, qc ---------------------------------------

def build(conn: sqlite3.Connection, clip_id: str, *, force: bool = False) -> StageOutcome:
    """Take a clip as far as the review queue, resuming from wherever it stopped.

    A build that dies after the render but before QC used to leave the clip
    stranded: re-running it would re-render and re-title, paying twice for work
    already on disk. Each stage is skipped when its output is already there and
    still valid, so `resume` is just `build` on a clip that is not `planned`.
    `force` ignores all of that and redoes everything.
    """
    row = db.get(conn, clip_id)
    if row is None:
        raise KeyError(f"no clip {clip_id!r}")
    ch = channels.get(conn, row["channel_id"])
    cfg = settings.load()
    spent = 0.0

    existing = Path(row["video_path"]) if row["video_path"] else None
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
            frames = render.sample_frames(existing, _sample_times(info["duration_s"]))
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
            gen = generators.get(row["generator"])
            clip = gen.generate(
                seed=row["seed"],
                variant=row["variant"],
                params=json.loads(row["params_json"]),
                work_dir=cfg.work_dir / ch.id / clip_id,
            )
            info = render.probe(clip.video_path)
            loudness = render.loudness_lufs(clip.video_path)
            frames = render.sample_frames(clip.video_path, _sample_times(info["duration_s"]))
            if not frames:
                raise RuntimeError("could not sample any frame from the render")
            digest_hash = phash.clip_hash(frames)
            sameness = phash.max_similarity(
                digest_hash, db.known_phashes(conn, ch.id, exclude=clip_id)
            )

            db.update(
                conn,
                clip_id,
                status=RENDERED,
                video_path=str(clip.video_path),
                render_desc=clip.description,
                facts_json=json.dumps(clip.facts, default=str),
                duration_s=info["duration_s"],
                width=info["width"],
                height=info["height"],
                fps=info["fps"],
                loudness_lufs=loudness,
                phash=digest_hash,
                sameness=round(sameness, 4),
            )
            # The silent mp4 and the wav are dead the moment the mux lands.
            swept = gc.sweep_intermediates(clip.video_path.parent)
            logs.event(
                "clip.rendered", channel=ch.id, clip=clip_id,
                duration_s=info["duration_s"], loudness_lufs=loudness,
                sameness=round(sameness, 4), facts=clip.facts,
                mb_reclaimed=swept.mb,
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
            meta = _Written(
                title=row["title"],
                description=row["description"] or "",
                hashtags=json.loads(row["hashtags_json"]),
            )
            logs.event("clip.metadata_reused", channel=ch.id, clip=clip_id, title=meta.title)
        else:
            meta, cost = metadata_agent.write_metadata(
            description=clip.description,
                facts=clip.facts,
                hook=row["hook"] or "",
            rules=ch.rules(),
                recent_titles=[r["title"] for r in recent if r["title"]],
                frames=frames,
            )
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
                title=meta.title, hashtags=meta.hashtags, cost_usd=round(cost, 6),
            )
    except Exception as exc:
        db.add_cost(conn, clip_id, spent)
        db.update(conn, clip_id, status=FAILED, reject_reason=f"metadata: {exc}")
        logs.event(
            "clip.failed", level="error", channel=ch.id, clip=clip_id,
            stage="metadata", error=str(exc),
        )
        return StageOutcome(clip_id, FAILED, f"metadata failed: {exc}", spent)

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


def build_all(
    conn: sqlite3.Connection, channel: Channel | str | None, limit: int = 20
) -> list[StageOutcome]:
    ch = resolve(conn, channel)
    return [build(conn, row["id"]) for row in db.by_status(conn, ch.id, PLANNED, limit)]


# --- the agent-driven path ---------------------------------------------------
#
# Everything above assumes this project's own agents supply the judgment, which
# costs an Anthropic key. When the caller is already a model — Codex or Claude
# over MCP — that is a second brain nobody needs to pay for. These three let the
# caller do the thinking and keep the machine doing the measuring.
#
# The split is the whole point and it is not negotiable: the caller supplies
# judgment, the server keeps the arithmetic. Aspect ratio, duration, loudness
# and sameness are measured here from the actual file every time. An agent
# cannot argue its way past the sameness check, because it is never asked.

def create_and_render(
    conn: sqlite3.Connection,
    channel: Channel | str | None,
    *,
    variant: str,
    generator: str = "physics",
    seed: int | None = None,
    hook: str = "",
    why: str = "",
) -> tuple[str, list[bytes], dict]:
    """Render one clip with no model involved. Returns (clip_id, frames, facts)."""
    import random

    ch = resolve(conn, channel)
    if not ch.allows(generator, variant):
        raise ValueError(
            f"{ch.id} does not allow {generator}/{variant}; "
            f"allowed: {ch.variants or 'any ready module'}"
        )
    used = {r["seed"] for r in conn.execute("SELECT seed FROM clips").fetchall()}
    rng = random.Random()
    while seed is None or seed in used:
        seed = rng.randrange(2**31 - 1)

    clip_id = db.insert_clip(
        conn, channel_id=ch.id, generator=generator, variant=variant, seed=seed,
        params={}, hook=hook, plan_why=why or "created by an external agent",
    )
    logs.event(
        "clip.planned", channel=ch.id, clip=clip_id, generator=generator,
        variant=variant, seed=seed, hook=hook, by="agent",
    )

    gen = generators.get(generator)
    clip = gen.generate(
        seed=seed, variant=variant, params={},
        work_dir=settings.load().work_dir / ch.id / clip_id,
    )
    info = render.probe(clip.video_path)
    loudness = render.loudness_lufs(clip.video_path)
    frames = render.sample_frames(clip.video_path, _sample_times(info["duration_s"]))
    if not frames:
        raise RuntimeError("could not sample any frame from the render")
    digest_hash = phash.clip_hash(frames)
    sameness = phash.max_similarity(
        digest_hash, db.known_phashes(conn, ch.id, exclude=clip_id)
    )
    db.update(
        conn, clip_id, status=RENDERED, video_path=str(clip.video_path),
        render_desc=clip.description, facts_json=json.dumps(clip.facts, default=str),
        duration_s=info["duration_s"], width=info["width"], height=info["height"],
        fps=info["fps"], loudness_lufs=loudness, phash=digest_hash,
        sameness=round(sameness, 4),
    )
    swept = gc.sweep_intermediates(clip.video_path.parent)
    logs.event(
        "clip.rendered", channel=ch.id, clip=clip_id, duration_s=info["duration_s"],
        loudness_lufs=loudness, sameness=round(sameness, 4), facts=clip.facts,
        mb_reclaimed=swept.mb, by="agent",
    )
    facts = {
        **info,
        "loudness_lufs": loudness,
        "sameness": round(sameness, 4),
        "shows": clip.description,
        "generator_facts": clip.facts,
        # Measured here, reported so the caller can see what it is judged against.
        "hard_failures": qc.hard_failures(
            probe=info, loudness_lufs=loudness, sameness=sameness
        ),
    }
    return clip_id, frames, facts


def attach_metadata(conn: sqlite3.Connection, clip_id: str, meta) -> None:
    """Store a title written by the caller. Validated exactly as the agent's is."""
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    db.update(
        conn, clip_id, status=DESCRIBED, title=meta.title,
        description=meta.description, hashtags_json=json.dumps(meta.hashtags),
    )
    logs.event(
        "clip.described", channel=row["channel_id"], clip=clip_id,
        title=meta.title, hashtags=meta.hashtags, cost_usd=0.0, by="agent",
    )


def apply_qc(conn: sqlite3.Connection, clip_id: str, verdict) -> tuple[bool, str]:
    """Combine the caller's judgment with this machine's measurements."""
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    if not row["title"]:
        raise ValueError(f"{clip_id} has no title yet; submit metadata first")
    info = {
        "width": row["width"], "height": row["height"],
        "fps": row["fps"], "duration_s": row["duration_s"],
    }
    failures = qc.hard_failures(
        probe=info, loudness_lufs=row["loudness_lufs"], sameness=row["sameness"] or 0.0
    )
    passed, reason = qc.decide(verdict, failures)
    db.update(
        conn, clip_id,
        status=AWAITING_APPROVAL if passed else QC_REJECTED,
        qc_json=verdict.model_dump_json(),
        reject_reason=None if passed else reason,
    )
    logs.event(
        "clip.qc", level="info" if passed else "warn", channel=row["channel_id"],
        clip=clip_id, passed=passed, hook_strength=verdict.hook_strength,
        policy_risk=verdict.policy_risk, looks_templated=verdict.looks_templated,
        hard_failures=failures, reason=reason or None, by="agent",
    )
    return passed, reason


STUCK = (RENDERED, DESCRIBED)


def stuck(conn: sqlite3.Connection, channel_id: str, *, include_failed: bool = False):
    """Clips that stopped between stages, oldest first."""
    statuses = list(STUCK) + ([FAILED] if include_failed else [])
    marks = ", ".join("?" for _ in statuses)
    return conn.execute(
        f"""SELECT * FROM clips WHERE channel_id = ? AND status IN ({marks})
            ORDER BY created_at""",
        (channel_id, *statuses),
    ).fetchall()


def resume(
    conn: sqlite3.Connection,
    channel: Channel | str | None,
    *,
    include_failed: bool = False,
    limit: int = 20,
) -> list[StageOutcome]:
    """Push stranded clips the rest of the way, reusing what is already on disk."""
    ch = resolve(conn, channel)
    rows = stuck(conn, ch.id, include_failed=include_failed)[:limit]
    out = []
    for row in rows:
        logs.event("clip.resumed", channel=ch.id, clip=row["id"], was=row["status"])
        out.append(build(conn, row["id"]))
    return out


# --- stage 5: the human gate -------------------------------------------------

def queue(conn: sqlite3.Connection, channel: Channel | str | None) -> list[sqlite3.Row]:
    ch = resolve(conn, channel)
    return db.by_status(conn, ch.id, AWAITING_APPROVAL)


def approve(conn: sqlite3.Connection, clip_id: str) -> None:
    row = db.get(conn, clip_id)
    if row is None or row["status"] != AWAITING_APPROVAL:
        raise ValueError(f"{clip_id} is not awaiting approval")
    db.update(conn, clip_id, status=APPROVED)
    logs.event("clip.approved", channel=row["channel_id"], clip=clip_id, title=row["title"])


def reject(conn: sqlite3.Connection, clip_id: str, reason: str) -> None:
    row = db.get(conn, clip_id)
    if row is None:
        raise ValueError(f"no clip {clip_id}")
    db.update(conn, clip_id, status=QC_REJECTED, reject_reason=f"human: {reason}")
    logs.event(
        "clip.rejected", level="warn", channel=row["channel_id"], clip=clip_id,
        reason=reason,
    )


# --- stage 6: publish --------------------------------------------------------

def publish_approved(
    conn: sqlite3.Connection, channel: Channel | str | None, *, dry_run: bool = False
) -> list[StageOutcome]:
    ch = resolve(conn, channel)
    driver = publish.get(ch.driver, ch)
    results = []
    for row in db.by_status(conn, ch.id, APPROVED):
        if dry_run:
            results.append(
                StageOutcome(row["id"], APPROVED, f"would publish via {ch.driver}")
            )
            continue
        try:
            result = driver.publish(
                clip_id=row["id"],
                video_path=Path(row["video_path"]),
                title=row["title"],
                description=row["description"],
                hashtags=json.loads(row["hashtags_json"] or "[]"),
            )
            db.update(
                conn,
                row["id"],
                status=PUBLISHED,
                platform=result.platform,
                remote_id=result.remote_id,
                published_at=db.now(),
            )
            logs.event(
                "clip.published", channel=ch.id, clip=row["id"],
                platform=result.platform, remote_id=result.remote_id,
                title=row["title"], driver=ch.driver,
            )
            results.append(StageOutcome(row["id"], PUBLISHED, result.note))
        except Exception as exc:
            logs.event(
                "clip.publish_failed", level="error", channel=ch.id,
                clip=row["id"], error=str(exc),
            )
            results.append(StageOutcome(row["id"], APPROVED, f"publish failed: {exc}"))
    return results


# --- stage 7: metrics and the feedback loop ---------------------------------

def pull_metrics(
    conn: sqlite3.Connection, channel: Channel | str | None
) -> list[StageOutcome]:
    ch = resolve(conn, channel)
    driver = publish.get(ch.driver, ch)
    results = []
    for row in db.by_status(conn, ch.id, PUBLISHED, limit=500):
        if not row["remote_id"]:
            continue
        try:
            metrics = driver.fetch_metrics(row["remote_id"])
            db.update(
                conn,
                row["id"],
                views=metrics.views,
                likes=metrics.likes,
                avg_view_pct=metrics.avg_view_pct,
                swipe_away_pct=metrics.swipe_away_pct,
                metrics_at=db.now(),
            )
            results.append(StageOutcome(row["id"], PUBLISHED, f"views={metrics.views}"))
        except Exception as exc:
            results.append(StageOutcome(row["id"], PUBLISHED, f"metrics failed: {exc}"))
    return results


def set_metrics(
    conn: sqlite3.Connection,
    clip_id: str,
    *,
    views: int,
    avg_view_pct: float,
    swipe_away_pct: float,
    likes: int = 0,
) -> None:
    """For the manual driver: type in what YouTube Studio shows you."""
    if db.get(conn, clip_id) is None:
        raise ValueError(f"no clip {clip_id}")
    db.update(
        conn,
        clip_id,
        views=views,
        likes=likes,
        avg_view_pct=avg_view_pct,
        swipe_away_pct=swipe_away_pct,
        metrics_at=db.now(),
    )


def digest(
    conn: sqlite3.Connection, channel: Channel | str | None, *, apply_rules: bool
) -> tuple[str, float, int]:
    ch = resolve(conn, channel)
    rows = db.published_with_metrics(conn, ch.id)
    if not rows:
        return (f"No published clip on {ch.name} has metrics yet.", 0.0, 0)
    result, cost, allowed = analyst.digest(rows)
    body = analyst.render_digest(result, len(rows), allowed)
    applied = 0
    if apply_rules and result.proposed_rules:
        ch.rules()  # make sure the file exists before appending to it
        applied = analyst.apply_rules(result.proposed_rules, ch.rules_path)
    db.record_digest(
        conn,
        channel_id=ch.id,
        n_published=len(rows),
        body=body,
        rules_applied=bool(applied),
        # Kept whether or not they were applied, so the Rules screen can offer
        # them one at a time instead of forcing all-or-nothing.
        proposals=result.proposed_rules,
    )
    return body, cost, applied
