"""Judging what came out: approve, reject, and the ways back.

A rejected clip is not a dead one. `restore` puts it back in the queue,
`rehook` re-renders it with a different opening caption, and the bin holds
what you threw away until you say to destroy it.
"""

from __future__ import annotations

import json
import sys

from .. import channels, db, pipeline


def _print_row(row) -> None:
    verdict = json.loads(row["qc_json"] or "{}")
    print(f"\n{row['id']}  {row['generator']}/{row['variant']} seed={row['seed']}")
    print(f"  title      {row['title']}")
    print(f"  hashtags   {' '.join(json.loads(row['hashtags_json'] or '[]'))}")
    print(f"  file       {db.video_file(row)}")
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


def cmd_restore(args) -> int:
    with db.connect() as conn:
        for clip_id in args.clip_ids:
            pipeline.restore(conn, clip_id)
            print(f"{clip_id} back in the queue")
    return 0


def cmd_retitle(args) -> int:
    with db.connect() as conn:
        out = pipeline.retitle(conn, args.clip_id, args.title, by="human", why=args.why or "")
    print(f"{out['clip']}: {out['was']!r} -> {out['title']!r}  (change #{out['changes']})")
    if out["needs_manual_update"]:
        print("published on a manual channel: change it in YouTube Studio as well")
    return 0


def cmd_rehook(args) -> int:
    if bool(args.text) == bool(args.measured):
        print("give a caption, or --measured to let the render choose one", file=sys.stderr)
        return 2
    with db.connect() as conn:
        outcome = pipeline.rehook(conn, args.clip_id, None if args.measured else args.text)
    print(f"{outcome.clip_id} {outcome.status}: {outcome.detail}")
    return 0 if outcome.status != "failed" else 1


def cmd_bin(args) -> int:
    with db.connect() as conn:
        if args.destroy:
            if not args.yes:
                print("destroying deletes the render directory and the row; add --yes", file=sys.stderr)
                return 2
            for clip_id in pipeline.destroy_clips(conn, args.clip_ids):
                print(f"{clip_id} destroyed")
        elif args.undo:
            for clip_id in pipeline.unbin_clips(conn, args.clip_ids):
                print(f"{clip_id} back from the bin")
        else:
            for clip_id in pipeline.bin_clips(conn, args.clip_ids):
                print(f"{clip_id} binned")
    return 0


def add(sub) -> None:
    sub.add_parser("queue", help="clips awaiting your approval", description="clips awaiting your approval").set_defaults(func=cmd_queue)

    p = sub.add_parser("approve", help="approve one or more clips", description="approve one or more clips")
    p.add_argument("clip_ids", nargs="+")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("reject", help="reject a clip with a reason", description="reject a clip with a reason")
    p.add_argument("clip_id")
    p.add_argument("reason")
    p.set_defaults(func=cmd_reject)

    p = sub.add_parser("restore", help="put a rejected clip back in the review queue", description="put a rejected clip back in the review queue")
    p.add_argument("clip_ids", nargs="+")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("retitle", help="change a title, keeping the old one and its numbers", description="change a title, keeping the old one and its numbers")
    p.add_argument("clip_id")
    p.add_argument("title")
    p.add_argument("--why", default="")
    p.set_defaults(func=cmd_retitle)

    p = sub.add_parser("rehook", help="re-render an unpublished clip with a new opening caption", description="re-render an unpublished clip with a new opening caption")
    p.add_argument("clip_id")
    p.add_argument("text", nargs="?", default=None)
    p.add_argument("--measured", action="store_true",
                   help="drop any fixed caption and let the render choose from what it measures")
    p.set_defaults(func=cmd_rehook)

    p = sub.add_parser("bin", help="move clips to the bin, bring them back, or destroy them", description="move clips to the bin, bring them back, or destroy them")
    p.add_argument("clip_ids", nargs="+")
    p.add_argument("--undo", action="store_true", help="bring binned clips back")
    p.add_argument("--destroy", action="store_true", help="delete binned clips and their files for good")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_bin)
