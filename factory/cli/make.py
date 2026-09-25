"""Making clips: what to make, making it, and the queue agents pull from.

`plan` and `build` are the built-in agents doing it; `tasks` and `work` are
the same job handed to an agent over MCP. `render-check` is neither — one
clip straight out of the generator, no agents and no database, for when you
are changing the renderer.
"""

from __future__ import annotations

import json
import shutil

from .. import channels, db, generators, phash, pipeline, render, settings, tasks
from ..agents import qc
from ..models import AWAITING_APPROVAL


def cmd_plan(args) -> int:
    with db.connect() as conn:
        channel = channels.resolve(conn, args.channel)
        run = db.start_run(conn, channel.id, "plan")
        try:
            ids, cost = pipeline.plan(conn, channel, args.count)
        except Exception as exc:
            db.finish_run(conn, run, status="failed", detail=str(exc))
            raise
        for clip_id in ids:
            row = db.get(conn, clip_id)
            print(
                f"{clip_id}  {row['generator']}/{row['variant']} seed={row['seed']}\n"
                f"  hook: {row['hook']}\n  why:  {row['plan_why']}"
            )
        db.finish_run(
            conn, run, status="ok", detail=f"{len(ids)} planned", cost_usd=cost
        )
        print(f"\n{channel.name}: planned {len(ids)} clip(s), ${cost:.4f}")
    return 0


def cmd_build(args) -> int:
    with db.connect() as conn:
        channel = channels.resolve(conn, args.channel)
        run = db.start_run(conn, channel.id, "build")
        outcomes = pipeline.build_all(conn, channel, limit=args.limit)
        if not outcomes:
            db.finish_run(conn, run, status="ok", detail="nothing planned")
            print("nothing planned; run `factory plan` first")
            return 0
        total = 0.0
        for outcome in outcomes:
            print(f"{outcome.clip_id}  {outcome.status:18} {outcome.detail}")
            total += outcome.cost_usd
        passed = sum(1 for o in outcomes if o.status == AWAITING_APPROVAL)
        db.finish_run(
            conn, run, status="ok",
            detail=f"{passed}/{len(outcomes)} reached the queue", cost_usd=total,
        )
        print(f"\n{passed}/{len(outcomes)} reached the queue, ${total:.4f}")
    return 0


def cmd_tasks(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        if args.action == "list":
            for r in db.tasks(conn, ch.id, args.status):
                t = tasks.as_dict(r)
                who = f" by {t['claimed_by']}" if t["claimed_by"] else ""
                tail = t["error"] or (t["result"] or {}).get("summary") or (t["result"] or {}).get("detail") or ""
                print(f"#{t['id']:<4} {t['kind']:10s} {t['status']:9s}{who:16s} {json.dumps(t['params'])}  {tail}")
            return 0
        if args.action == "cancel":
            for tid in str(args.value).split(","):
                db.cancel_task(conn, int(tid)); print(f"task #{tid} cancelled")
            return 0
        if args.action == "delete":
            removed = db.delete_tasks(conn, [int(x) for x in str(args.value).split(",")])
            print(f"deleted {len(removed)} task(s): {removed}")
            return 0
        if args.action == "clear":
            print(f"cleared {db.clear_finished_tasks(conn, ch.id)} finished task(s) on {ch.id}")
            return 0
        params = {k: v for k, v in (("generator", args.generator), ("variant", args.variant), ("seed", args.seed),
                                    ("stage", args.stage), ("background", args.background)) if v is not None}
        ids = tasks.enqueue(conn, ch.id, args.value, params, count=args.count, priority=args.priority)
        print(f"queued {len(ids)} × {args.value} on {ch.id}: #{ids[0]}" + (f"–#{ids[-1]}" if len(ids) > 1 else ""))
    return 0


def cmd_work(args) -> int:
    with db.connect() as conn:
        done = tasks.work(conn, channel_id=args.channel, once=args.once)
    for t in done:
        print(f"task #{t['id']} {t['kind']}: {t['status']}  {t.get('error') or (t.get('result') or {}).get('detail', '')}")
    if not done:
        print("nothing the built-in agents can do is queued")
    return 0 if all(t["status"] == "done" for t in done) else 1


def cmd_resume(args) -> int:
    with db.connect() as conn:
        channel = channels.resolve(conn, args.channel)
        rows = pipeline.stuck(conn, channel.id, include_failed=args.include_failed)
        if not rows:
            print(f"{channel.name}: nothing stuck")
            return 0
        print(f"{channel.name}: {len(rows)} stuck clip(s)")
        for row in rows:
            print(f"  {row['id']}  {row['status']:<12} {row['title'] or row['hook'] or ''}")
        if args.dry_run:
            print("\nnothing was run; drop --dry-run to resume them")
            return 0
        run = db.start_run(conn, channel.id, "resume")
        outcomes = pipeline.resume(
            conn, channel, include_failed=args.include_failed, limit=args.limit
        )
        total = sum(o.cost_usd for o in outcomes)
        print()
        for outcome in outcomes:
            print(f"{outcome.clip_id}  {outcome.status:18} {outcome.detail}")
        db.finish_run(
            conn, run, status="ok", detail=f"{len(outcomes)} resumed", cost_usd=total
        )
        print(f"\n{len(outcomes)} resumed, ${total:.4f}")
    return 0


def cmd_render_check(args) -> int:
    """Render one clip end to end without calling any agent or touching the db."""
    cfg = settings.load()
    cfg.ensure_dirs()
    gen = generators.get(args.generator)
    label = f"check-{args.generator}-{args.variant}-{args.seed}"
    # A trial stage has weight 0, so a random pick never lands on it: naming it
    # is the only way to look at one, which is what this command is for.
    params = {"stage": args.stage} if args.stage else {}
    if args.cast:
        from .ops import cast_entrants

        params["cast"] = cast_entrants(args.cast, args.entrants)
    clip = gen.generate(
        seed=args.seed, variant=args.variant, params=params, work_dir=cfg.work_dir / label
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
    print(f"phash      {phash.clip_hash(frames)[:32]}...")
    print(f"facts      {json.dumps(clip.facts, default=str)}")
    print(f"says       {clip.description}")
    if clip.trace_path:
        print(f"trace      {clip.trace_path}")
    if failures:
        print("hard QC    FAIL")
        for failure in failures:
            print(f"           - {failure}")
        return 1
    print("hard QC    pass")
    return 0


def add(sub) -> None:
    p = sub.add_parser("plan", help="ask the Idea agent what to make", description="ask the Idea agent what to make")
    p.add_argument("--count", type=int, default=3)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("build", help="render, describe and QC everything planned", description="render, describe and QC everything planned")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("tasks", help="the queue agents pull from: add, list, cancel", description="the queue agents pull from: add, list, cancel")
    p.add_argument("action", choices=["add", "list", "cancel", "delete", "clear"])
    p.add_argument("value", nargs="?", help="kind to add, id(s) to cancel/delete (comma-separated), or nothing for clear")
    p.add_argument("--variant"); p.add_argument("--generator"); p.add_argument("--seed", type=int)
    p.add_argument("--stage", "--course", dest="stage", help="zigzag, pegboard, bumpers, funnels, gauntlet or cascade"); p.add_argument("--background", help="hex colour")
    p.add_argument("--count", type=int, default=1); p.add_argument("--priority", type=int, default=0)
    p.add_argument("--status")
    p.set_defaults(func=cmd_tasks)

    p = sub.add_parser("work", help="run the queue with the built-in agents (needs a ready provider)", description="run the queue with the built-in agents (needs a ready provider)")
    p.add_argument("--once", action="store_true")
    p.set_defaults(func=cmd_work)

    p = sub.add_parser("resume", help="push clips that stopped between stages the rest of the way", description="push clips that stopped between stages the rest of the way")
    p.add_argument("--include-failed", action="store_true", dest="include_failed")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("render-check", help="render one clip with no agents and no database", description="render one clip with no agents and no database")
    p.add_argument("--generator", default="physics")
    p.add_argument("--variant", default="marble_race")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--stage", default=None, help="race stage id; default is the seed's own weighted pick")
    p.add_argument("--cast", help="race this channel's cast (channels/<id>/cast.toml) instead of the theme's marbles")
    p.add_argument("--entrants", help="with --cast: these ids, comma-separated (default: the L01 regulars)")
    p.set_defaults(func=cmd_render_check)
