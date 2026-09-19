"""Command line for the daily loop.

Your 30 minutes, in order:

    factory plan --count 3      # 5 min   read what it proposes
    factory build               # 0 min   runs while you do something else
    factory queue               # 15 min  approve by exception
    factory approve <id>
    factory publish
    factory digest              # 10 min  once a week is enough at first

Every command works on one channel. With a single active channel it is picked
for you; with several, pass --channel.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from . import channels, db, generators, llm, phash, pipeline, render, settings
from .agents import qc
from .models import AWAITING_APPROVAL


def _print_row(row) -> None:
    verdict = json.loads(row["qc_json"] or "{}")
    print(f"\n{row['id']}  {row['generator']}/{row['variant']} seed={row['seed']}")
    print(f"  title      {row['title']}")
    print(f"  hashtags   {' '.join(json.loads(row['hashtags_json'] or '[]'))}")
    print(f"  file       {row['video_path']}")
    print(
        f"  technical  {row['duration_s']}s {row['width']}x{row['height']} "
        f"@{row['fps']}fps  {row['loudness_lufs']} LUFS  sameness={row['sameness']}"
    )
    if verdict:
        print(
            f"  qc         hook={verdict.get('hook_strength')}/5 "
            f"policy={verdict.get('policy_risk')} templated={verdict.get('looks_templated')}"
        )
        for reason in verdict.get("reasons", []):
            print(f"             - {reason}")
    print(f"  cost       ${row['cost_usd']:.4f}")


def cmd_init(args) -> int:
    cfg = settings.load()
    cfg.ensure_dirs()
    with db.connect() as conn:
        steps = db.migrate(conn)
        for step in steps:
            print(f"migrated: {step}")
        if not channels.all_channels(conn):
            channel = channels.create(conn, name="Main channel", channel_id=channels.DEFAULT_ID)
            print(f"created channel {channel.id}")
    print(f"ready: {cfg.db_path}")
    return 0


def cmd_doctor(args) -> int:
    cfg = settings.load()
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        print(f"{tool:9} {path or 'MISSING — brew install ffmpeg'}")
        ok = ok and bool(path)
    for module in ("anthropic", "pydantic", "pymunk", "PIL", "numpy", "fastapi"):
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
    with db.connect() as conn:
        found = channels.all_channels(conn)
    print(f"channels  {len(found)} ({', '.join(c.id for c in found) or 'none — run factory init'})")
    print(f"model     {cfg.llm['model']}")
    return 0 if ok else 1


def cmd_generators(args) -> int:
    for name, gen in generators.all_generators().items():
        flag = "ready" if getattr(gen, "ready", True) else "stub"
        print(f"{name:15} [{flag}] variants: {', '.join(gen.variants)}")
    return 0


# --- channels ----------------------------------------------------------------

def cmd_channels_list(args) -> int:
    with db.connect() as conn:
        found = channels.all_channels(conn)
        if not found:
            print("no channels yet; run `factory channels add \"Name\"`")
            return 0
        for channel in found:
            counts = db.status_counts(conn, channel.id)
            state = "active" if channel.active else "paused"
            print(f"\n{channel.id}  {channel.name}  [{state}]")
            print(f"  handle    {channel.handle or '—'} on {channel.platform}")
            print(f"  driver    {channel.driver}")
            print(f"  modules   {', '.join(channel.variants) or 'any ready module'}")
            print(f"  cadence   {channel.cadence}/day")
            print(f"  clips     {counts or 'none yet'}")
            print(f"  rules     {channel.rules_path}")
            print(f"  spend     ${db.spend(conn, channel.id):.4f}")
    return 0


def cmd_channels_add(args) -> int:
    with db.connect() as conn:
        channel = channels.create(
            conn,
            name=args.name,
            channel_id=args.id,
            handle=args.handle,
            platform=args.platform,
            driver=args.driver,
            variants=args.variant or [],
            cadence=args.cadence,
        )
    print(f"created {channel.id}: {channel.name}")
    print(f"rules at {channel.rules_path}")
    return 0


def cmd_channels_edit(args) -> int:
    fields = {}
    for key in ("name", "handle", "platform", "driver", "cadence"):
        value = getattr(args, key)
        if value is not None:
            fields[key] = value
    if args.variant:
        fields["variants"] = args.variant
    if args.pause:
        fields["active"] = 0
    if args.resume:
        fields["active"] = 1
    with db.connect() as conn:
        channel = channels.edit(conn, args.id, **fields)
    print(f"{channel.id}: {channel.name} [{'active' if channel.active else 'paused'}]")
    return 0


def cmd_runs(args) -> int:
    with db.connect() as conn:
        rows = db.recent_runs(conn, args.channel, limit=args.limit)
    if not rows:
        print("no runs recorded yet")
        return 0
    for row in rows:
        print(
            f"{row['started_at']}  {row['channel_id']:12} {row['kind']:14} "
            f"{row['status']:8} ${row['cost_usd']:.4f}  {row['detail'] or ''}"
        )
    return 0


# --- the loop ----------------------------------------------------------------

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


def cmd_queue(args) -> int:
    with db.connect() as conn:
        channel = channels.resolve(conn, args.channel)
        rows = pipeline.queue(conn, channel)
        if not rows:
            print(f"{channel.name}: queue empty")
            return 0
        for row in rows:
            _print_row(row)
        print(f"\n{channel.name}: {len(rows)} awaiting approval")
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
        channel = channels.resolve(conn, args.channel)
        run = db.start_run(conn, channel.id, "publish")
        outcomes = pipeline.publish_approved(conn, channel, dry_run=args.dry_run)
        if not outcomes:
            print("nothing approved")
        for outcome in outcomes:
            print(f"{outcome.clip_id}  {outcome.status:10} {outcome.detail}")
        db.finish_run(conn, run, status="ok", detail=f"{len(outcomes)} handled")
    return 0


def cmd_pull_metrics(args) -> int:
    with db.connect() as conn:
        channel = channels.resolve(conn, args.channel)
        for outcome in pipeline.pull_metrics(conn, channel):
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
        channel = channels.resolve(conn, args.channel)
        body, cost, applied = pipeline.digest(conn, channel, apply_rules=args.apply_rules)
        print(body)
        suffix = f", {applied} rule(s) written to {channel.rules_path}" if applied else ""
        print(f"\n${cost:.4f}{suffix}")
    return 0


def cmd_status(args) -> int:
    with db.connect() as conn:
        found = channels.all_channels(conn)
        if not found:
            print("no channels yet")
            return 0
        for channel in found:
            counts = db.status_counts(conn, channel.id)
            line = "  ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no clips"
            print(f"{channel.id:14} {line}   ${db.spend(conn, channel.id):.4f}")
        print(f"\ntotal spend ${db.spend(conn):.4f}")
    return 0


def cmd_render_check(args) -> int:
    """Render one clip end to end without calling any agent or touching the db."""
    from PIL import Image

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


def cmd_brand(args) -> int:
    from PIL import Image

    from . import brand

    cfg = settings.load()
    cfg.ensure_dirs()
    out = cfg.out_dir / "brand"
    out.mkdir(parents=True, exist_ok=True)
    for path in [
        brand.avatar(out / "avatar.png"),
        brand.banner(out / "banner.png", title=args.title, tagline=args.tagline),
    ]:
        with Image.open(path) as image:
            print(f"{path}  {image.width}x{image.height}")
    print("\navatar goes in Customization > Branding > Picture")
    print("banner goes in Customization > Branding > Banner image")
    return 0


def cmd_serve(args) -> int:
    from . import web

    print(f"http://{args.host}:{args.port}   (ctrl-c to stop)")
    web.serve(host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    parser.add_argument(
        "--channel", default=None,
        help="channel id; optional while only one channel is active",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database, migrate, seed a channel").set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="check ffmpeg, dependencies, credentials").set_defaults(func=cmd_doctor)
    sub.add_parser("generators", help="list generator modules").set_defaults(func=cmd_generators)
    sub.add_parser("status", help="counts by stage per channel").set_defaults(func=cmd_status)

    channel_parser = sub.add_parser("channels", help="add, list and edit channels")
    channel_sub = channel_parser.add_subparsers(dest="channel_command", required=True)
    channel_sub.add_parser("list").set_defaults(func=cmd_channels_list)

    p = channel_sub.add_parser("add", help="create a channel")
    p.add_argument("name")
    p.add_argument("--id", default=None, help="internal id; defaults to a slug of the name")
    p.add_argument("--handle", default=None)
    p.add_argument("--platform", default="youtube")
    p.add_argument("--driver", default=None, choices=["manual", "youtube"])
    p.add_argument("--variant", action="append", help="generator/variant; repeatable")
    p.add_argument("--cadence", type=int, default=1)
    p.set_defaults(func=cmd_channels_add)

    p = channel_sub.add_parser("edit", help="change a channel")
    p.add_argument("id")
    p.add_argument("--name", default=None)
    p.add_argument("--handle", default=None)
    p.add_argument("--platform", default=None)
    p.add_argument("--driver", default=None, choices=["manual", "youtube"])
    p.add_argument("--variant", action="append", help="replaces the whole list")
    p.add_argument("--cadence", type=int, default=None)
    p.add_argument("--pause", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.set_defaults(func=cmd_channels_edit)

    p = sub.add_parser("runs", help="recent job history")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_runs)

    p = sub.add_parser("plan", help="ask the Idea agent what to make")
    p.add_argument("--count", type=int, default=3)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("build", help="render, describe and QC everything planned")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_build)

    sub.add_parser("queue", help="clips awaiting your approval").set_defaults(func=cmd_queue)

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

    sub.add_parser("pull-metrics", help="refresh metrics from the platform").set_defaults(func=cmd_pull_metrics)

    p = sub.add_parser("set-metrics", help="enter metrics by hand (manual driver)")
    p.add_argument("clip_id")
    p.add_argument("--views", type=int, required=True)
    p.add_argument("--avg-view-pct", type=float, required=True, dest="avg_view_pct")
    p.add_argument("--swipe-away-pct", type=float, required=True, dest="swipe_away_pct")
    p.add_argument("--likes", type=int, default=0)
    p.set_defaults(func=cmd_set_metrics)

    p = sub.add_parser("digest", help="Analyst digest over published clips")
    p.add_argument("--apply-rules", action="store_true")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("render-check", help="render one clip with no agents and no database")
    p.add_argument("--generator", default="physics")
    p.add_argument("--variant", default="marble_race")
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(func=cmd_render_check)

    p = sub.add_parser("brand", help="draw the channel avatar and banner")
    p.add_argument("--title", default="GRAVITY LAB")
    p.add_argument("--tagline", default="no talking  ·  sound on")
    p.set_defaults(func=cmd_brand)

    p = sub.add_parser("serve", help="open the review UI in a browser")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

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
