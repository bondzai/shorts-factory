"""Command line for the daily loop.

Your 30 minutes, in order:

    factory plan --count 3      # 5 min   read what it wants to make
    factory build               # 0 min   runs while you do something else
    factory queue               # 15 min  approve by exception
    factory approve <id>
    factory publish
    factory digest              # 10 min  once a week is enough at first
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from . import db, generators, llm, phash, pipeline, render, settings
from .agents import qc
from .models import AWAITING_APPROVAL


def _print_row(row) -> None:
    qc = json.loads(row["qc_json"] or "{}")
    print(f"\n{row['id']}  {row['generator']}/{row['variant']} seed={row['seed']}")
    print(f"  title      {row['title']}")
    print(f"  hashtags   {' '.join(json.loads(row['hashtags_json'] or '[]'))}")
    print(f"  file       {row['video_path']}")
    print(
        f"  technical  {row['duration_s']}s {row['width']}x{row['height']} "
        f"@{row['fps']}fps  {row['loudness_lufs']} LUFS  sameness={row['sameness']}"
    )
    if qc:
        print(
            f"  qc         hook={qc.get('hook_strength')}/5 "
            f"policy={qc.get('policy_risk')} templated={qc.get('looks_templated')}"
        )
        for reason in qc.get("reasons", []):
            print(f"             - {reason}")
    print(f"  cost       ${row['cost_usd']:.4f}")


def cmd_init(args) -> int:
    cfg = settings.load()
    cfg.ensure_dirs()
    with db.connect():
        pass
    print(f"ready: {cfg.db_path}")
    return 0


def cmd_doctor(args) -> int:
    cfg = settings.load()
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        print(f"{tool:9} {path or 'MISSING — brew install ffmpeg'}")
        ok = ok and bool(path)
    for module in ("anthropic", "pydantic", "pymunk", "PIL", "numpy"):
        try:
            __import__(module)
            print(f"{module:9} ok")
        except ImportError:
            print(f"{module:9} MISSING — pip install -e .")
            ok = False
    # Constructing the client never fails, so checking that proves nothing —
    # the SDK only raises when a request goes out. Look at what it resolved.
    try:
        client = llm.client()
        if client.api_key or client.auth_token:
            print("auth      ok")
        else:
            print(
                "auth      MISSING — put ANTHROPIC_API_KEY=... in this repo's .env,\n"
                "          export it, or run `ant auth login`. An export only\n"
                "          exists in the terminal you typed it in."
            )
            ok = False
    except Exception as exc:
        print(f"auth      {exc}")
        ok = False
    print(f"driver    {cfg.raw['publish']['driver']}")
    print(f"model     {cfg.llm['model']}")
    return 0 if ok else 1


def cmd_generators(args) -> int:
    for name, gen in generators.all_generators().items():
        flag = "ready" if getattr(gen, "ready", True) else "stub"
        print(f"{name:15} [{flag}] variants: {', '.join(gen.variants)}")
    return 0


def cmd_render_check(args) -> int:
    """Render one clip end to end without calling any agent or touching the db.

    This is the cheap way to prove the ffmpeg path works, or to look at what a
    generator change did, without spending anything on the API.
    """
    cfg = settings.load()
    cfg.ensure_dirs()
    gen = generators.get(args.generator)
    label = f"check-{args.generator}-{args.variant}-{args.seed}"
    clip = gen.generate(
        seed=args.seed, variant=args.variant, params={}, work_dir=cfg.work_dir / label
    )
    info = render.probe(clip.video_path)
    loudness = render.loudness_lufs(clip.video_path)
    times = [
        min(0.3, info["duration_s"] / 10),
        info["duration_s"] * 0.35,
        info["duration_s"] * 0.7,
        max(0.0, info["duration_s"] - 0.35),
    ]
    frames = render.sample_frames(clip.video_path, times)
    failures = qc.hard_failures(probe=info, loudness_lufs=loudness, sameness=0.0)

    destination = cfg.out_dir / f"{label}.mp4"
    shutil.copy2(clip.video_path, destination)

    print(f"file       {destination}")
    print(f"size       {destination.stat().st_size / 1_000_000:.1f} MB")
    print(
        f"technical  {info['duration_s']}s {info['width']}x{info['height']} "
        f"@{info['fps']}fps  {loudness} LUFS"
    )
    print(f"frames     sampled {len(frames)} for hashing and QC")
    print(f"phash      {phash.clip_hash(frames)[:32]}...")
    print(f"facts      {json.dumps(clip.facts, default=str)}")
    print(f"says       {clip.description}")
    if failures:
        print("hard QC    FAIL")
        for failure in failures:
            print(f"           - {failure}")
        return 1
    print("hard QC    pass")
    return 0


def cmd_plan(args) -> int:
    with db.connect() as conn:
        ids, cost = pipeline.plan(conn, args.count)
        for clip_id in ids:
            row = db.get(conn, clip_id)
            print(
                f"{clip_id}  {row['generator']}/{row['variant']} seed={row['seed']}\n"
                f"  hook: {row['hook']}\n  why:  {row['plan_why']}"
            )
        print(f"\nplanned {len(ids)} clip(s), ${cost:.4f}")
    return 0


def cmd_build(args) -> int:
    with db.connect() as conn:
        outcomes = pipeline.build_all(conn, limit=args.limit)
        if not outcomes:
            print("nothing planned; run `factory plan` first")
            return 0
        total = 0.0
        for outcome in outcomes:
            print(f"{outcome.clip_id}  {outcome.status:18} {outcome.detail}")
            total += outcome.cost_usd
        passed = sum(1 for o in outcomes if o.status == AWAITING_APPROVAL)
        print(f"\n{passed}/{len(outcomes)} reached the queue, ${total:.4f}")
    return 0


def cmd_queue(args) -> int:
    with db.connect() as conn:
        rows = pipeline.queue(conn)
        if not rows:
            print("queue empty")
            return 0
        for row in rows:
            _print_row(row)
        print(f"\n{len(rows)} awaiting approval")
    return 0


def cmd_approve(args) -> int:
    with db.connect() as conn:
        for clip_id in args.clip_ids:
            pipeline.approve(conn, clip_id)
            print(f"{clip_id} approved")
    return 0


def cmd_reject(args) -> int:
    with db.connect() as conn:
        pipeline.reject(conn, args.clip_id, args.reason)
        print(f"{args.clip_id} rejected: {args.reason}")
    return 0


def cmd_publish(args) -> int:
    with db.connect() as conn:
        outcomes = pipeline.publish_approved(conn, dry_run=args.dry_run)
        if not outcomes:
            print("nothing approved")
        for outcome in outcomes:
            print(f"{outcome.clip_id}  {outcome.status:10} {outcome.detail}")
    return 0


def cmd_pull_metrics(args) -> int:
    with db.connect() as conn:
        for outcome in pipeline.pull_metrics(conn):
            print(f"{outcome.clip_id}  {outcome.detail}")
    return 0


def cmd_set_metrics(args) -> int:
    with db.connect() as conn:
        pipeline.set_metrics(
            conn,
            args.clip_id,
            views=args.views,
            avg_view_pct=args.avg_view_pct,
            swipe_away_pct=args.swipe_away_pct,
            likes=args.likes,
        )
        print(f"{args.clip_id} metrics stored")
    return 0


def cmd_digest(args) -> int:
    with db.connect() as conn:
        body, cost, applied = pipeline.digest(conn, apply_rules=args.apply_rules)
        print(body)
        print(f"\n${cost:.4f}" + (f", {applied} rule(s) written to rules.md" if applied else ""))
    return 0


def cmd_status(args) -> int:
    with db.connect() as conn:
        counts = db.status_counts(conn)
        if not counts:
            print("no clips yet")
            return 0
        for status, n in sorted(counts.items()):
            print(f"{status:18} {n}")
        total = conn.execute("SELECT SUM(cost_usd) s FROM clips").fetchone()["s"] or 0
        print(f"\nmodel spend to date  ${total:.4f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database and data directories").set_defaults(
        func=cmd_init
    )
    sub.add_parser("doctor", help="check ffmpeg, dependencies, credentials").set_defaults(
        func=cmd_doctor
    )
    sub.add_parser("generators", help="list generator modules").set_defaults(
        func=cmd_generators
    )
    sub.add_parser("status", help="counts by stage, and spend").set_defaults(
        func=cmd_status
    )

    p = sub.add_parser(
        "render-check", help="render one clip with no agents and no database"
    )
    p.add_argument("--generator", default="physics")
    p.add_argument("--variant", default="marble_race")
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(func=cmd_render_check)

    p = sub.add_parser("plan", help="ask the Idea agent what to make")
    p.add_argument("--count", type=int, default=3)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("build", help="render, describe and QC everything planned")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_build)

    sub.add_parser("queue", help="clips awaiting your approval").set_defaults(
        func=cmd_queue
    )

    p = sub.add_parser("approve", help="approve one or more clips")
    p.add_argument("clip_ids", nargs="+")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="reject a clip with a reason")
    p.add_argument("clip_id")
    p.add_argument("reason")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("publish", help="publish approved clips")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_publish)

    sub.add_parser("pull-metrics", help="refresh metrics from the platform").set_defaults(
        func=cmd_pull_metrics
    )

    p = sub.add_parser("set-metrics", help="enter metrics by hand (manual driver)")
    p.add_argument("clip_id")
    p.add_argument("--views", type=int, required=True)
    p.add_argument("--avg-view-pct", type=float, required=True, dest="avg_view_pct")
    p.add_argument("--swipe-away-pct", type=float, required=True, dest="swipe_away_pct")
    p.add_argument("--likes", type=int, default=0)
    p.set_defaults(func=cmd_set_metrics)

    p = sub.add_parser("digest", help="Analyst digest over published clips")
    p.add_argument(
        "--apply-rules",
        action="store_true",
        help="write accepted rules into rules.md (ignored below the sample threshold)",
    )
    p.set_defaults(func=cmd_digest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
