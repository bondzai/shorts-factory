"""Running the place: what happened, what it is keeping, who it tells,
and the two long-running servers.
"""

from __future__ import annotations

import json
import time

from .. import db, gc, logs, mcp as mcp_server, notify, settings, stage_qa
from ..generators import physics


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


def cmd_logs(args) -> int:
    records = logs.read(
        limit=args.limit, channel=args.channel, level=args.level,
        event_name=args.event, clip=args.clip,
    )
    if not records:
        print("no events yet")
        return 0
    for record in reversed(records):
        mark = {"error": "!!", "warn": " !"}.get(record["level"], "  ")
        extra = {
            k: v for k, v in record.items()
            if k not in {"at", "level", "event", "channel", "clip", "actor"} and v is not None
        }
        who = record.get("actor") or "-"
        print(
            f"{record['at'][11:23]} {mark} {record['event']:<20} "
            f"{record.get('channel') or '-':<12} {record.get('clip') or '-':<13} "
            f"{who:<6} {json.dumps(extra, default=str, ensure_ascii=False)[:110]}"
        )
    return 0


def cmd_notify(args) -> int:
    sinks = notify.sinks()
    if not sinks:
        print("nothing to post to: set FACTORY_WEBHOOK_URL and/or FACTORY_TELEGRAM_TOKEN + FACTORY_TELEGRAM_CHAT_ID in .env")
        return 1
    where = ", ".join(f"{s['kind']} ({s['where']})" for s in sinks)

    if getattr(args, "daily", False):
        print(f"posting the daily reminder to {where}")
        sent = notify.daily(force=True)
        if not sent:
            print("nothing approved is waiting, so nothing was sent")
            return 0
    else:
        print(f"posting a test notification to {where} (paths and ids are secrets and stay unprinted)")
        sent = notify.post(
            "notify.test", "[test] shorts-factory can reach this endpoint",
            channel="test", kind="test", status="ok",
        )
    if not sent:
        print("event not in [notify] on = [...]; nothing was sent")
        return 1
    time.sleep(2)
    seen, failed = 0, 0
    for record in logs.read(limit=6, event_name="notify."):
        if record["event"] in ("notify.sent", "notify.failed") and seen < len(sinks):
            seen += 1
            failed += record["event"] == "notify.failed"
            print(f"{record.get('sink') or 'webhook'}: {record['event'].split('.')[1]} {record.get('status') or record.get('error') or ''}")
    if seen:
        return 1 if failed else 0
    print("no result logged yet; check `factory logs --event notify.`")
    return 0


def cmd_gc(args) -> int:
    before = gc.disk_usage()
    verb = "would free" if args.dry_run else "freed"
    print(f"data/work {before['work_mb']} MB · data/out {before['out_mb']} MB\n")

    leftovers = gc.sweep_all_intermediates(dry_run=args.dry_run)
    if leftovers.files:
        print(
            f"intermediates: {verb} {leftovers.mb} MB across {leftovers.files} "
            f"file(s) in {len(leftovers.clips)} directory(ies)"
        )

    with db.connect() as conn:
        swept = gc.sweep_clips(conn, dry_run=args.dry_run, channel_id=args.channel)
    if not swept.clips:
        print("settled clips: nothing old enough to remove")
    else:
        print(
            f"settled clips: {verb} {swept.mb} MB across {swept.files} file(s) "
            f"from {len(swept.clips)} clip(s)"
        )
        for clip_id in swept.clips:
            print(f"  {clip_id}")
    if not leftovers.files and not swept.clips:
        return 0
    if args.dry_run:
        print("\nnothing was deleted; drop --dry-run to do it")
    return 0


def cmd_stage_qa(args) -> int:
    """Measure stages over many seeds; optionally tune gravity; write the report."""
    wanted = args.stage or ([s.id for s in physics.STAGE_SPECS if s.composed] if args.composed
                            else [s.id for s in physics.STAGE_SPECS])
    unknown = [s for s in wanted if s not in physics.STAGE_BY_ID]
    if unknown:
        print(f"no stage {unknown}; have {sorted(physics.STAGE_BY_ID)}")
        return 2
    seeds = list(range(args.first_seed, args.first_seed + args.seeds))
    reports = []
    for stage in wanted:
        g = None
        if args.calibrate:
            g = stage_qa.calibrate(stage, list(range(args.first_seed + 5000, args.first_seed + 5000 + 10)))
            print(f"{stage}: calibrated gravity {g:.0f} (registry has {physics.STAGE_GRAVITY[stage]:.0f})")
        rep = stage_qa.run(stage, seeds, gravity_value=g)
        reports.append(rep)
        print(rep.row(), flush=True)
    if args.report:
        path = settings.ROOT / args.report
        path.write_text(stage_qa.report_markdown(reports, args.seeds), encoding="utf-8")
        print(f"wrote {path.relative_to(settings.ROOT)}")
    return 0 if all(r.passed for r in reports) else 1


def cmd_mcp(args) -> int:
    mcp_server.serve(allow_publish=args.allow_publish)
    return 0


def cmd_serve(args) -> int:
    from .. import web  # here: FastAPI costs 170 ms, and only this command needs it

    print(f"http://{args.host}:{args.port}   (ctrl-c to stop)")
    web.serve(host=args.host, port=args.port)
    return 0


def add(sub) -> None:
    p = sub.add_parser("runs", help="recent job history", description="recent job history")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_runs)

    p = sub.add_parser("logs", help="recent pipeline events", description="recent pipeline events")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--level", choices=list(("debug", "info", "warn", "error")), default=None)
    p.add_argument("--event", default=None, help="prefix, for example clip. or agent.")
    p.add_argument("--clip", default=None)
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("notify", help="post a test notification, or today's upload reminder, to the configured webhook", description="post a test notification, or today's upload reminder, to the configured webhook")
    p.add_argument("--daily", action="store_true", help="send the daily 'approved clips waiting' reminder now")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("gc", help="delete rendered files whose outcome is settled", description="delete rendered files whose outcome is settled")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_gc)

    p = sub.add_parser("stage-qa", help="measure race stages over many seeds: stalls, parked marbles, runner-ups, pace, drama",
                       description="measure race stages over many seeds: stalls, parked marbles, runner-ups, pace, drama")
    p.add_argument("--stage", action="append", help="a stage id; repeat for several (default: all)")
    p.add_argument("--composed", action="store_true", help="only the stages stacked from sections")
    p.add_argument("--seeds", type=int, default=16, help="seeds per stage (default 16)")
    p.add_argument("--first-seed", type=int, default=700)
    p.add_argument("--calibrate", action="store_true", help="tune gravity so the median finish lands mid-window, then measure")
    p.add_argument("--report", help="write the markdown table here, e.g. docs/06-stage-qa.md")
    p.set_defaults(func=cmd_stage_qa)

    p = sub.add_parser("mcp", help="run the MCP server on stdio so an agent can drive the factory")
    p.add_argument("--allow-publish", action="store_true",
                   help="let the agent approve and publish; off by default on purpose")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("serve", help="open the review UI in a browser", description="open the review UI in a browser")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)
