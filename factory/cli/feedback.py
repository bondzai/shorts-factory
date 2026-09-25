"""Lessons from the numbers: `factory feedback list|add|edit|rm`.

The same service as the Feedback screen and the MCP tools (factory/feedback.py).
Only adopted lessons reach the playbooks and the copy brain.
"""

from __future__ import annotations

import json
import sys

from .. import channels, db
from .. import feedback as service


def _line(i: dict) -> str:
    clips = f"  clips {', '.join(i['clip_ids'])}" if i["clip_ids"] else ""
    return (f"#{i['id']:<4} [{i['status']:<7}] {i['area']:<8} {i['observation']}"
            + (f"\n       → {i['action']}" if i["action"] else "")
            + (f"\n       evidence: {i['evidence']}" if i["evidence"] else "")
            + (f"\n       result: {i['result']}" if i["result"] else "")
            + (f"\n      {clips}" if clips else ""))


def cmd_list(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        items, total = service.list_(conn, ch.id, status=args.status, area=args.area, clip=args.clip)
    if args.json:
        print(json.dumps(items, indent=1, default=str))
        return 0
    if not items:
        print(f"No lessons on {ch.name}" + (" that match." if total == 0 and (args.status or args.area or args.clip) else " yet."))
        return 0
    for i in items:
        print(_line(i))
    return 0


def cmd_add(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        out = service.create(conn, ch.id, observation=args.observation, area=args.area,
                             evidence=args.evidence or "", clip_ids=args.clips or [],
                             action=args.action or "", status=args.status, source="manual",
                             created_by="cli")
    print(f"added #{out['id']}")
    print(_line(out))
    return 0


def cmd_edit(args) -> int:
    fields = {k: getattr(args, k) for k in ("observation", "area", "evidence", "action", "status", "result")
              if getattr(args, k) is not None}
    if args.clips is not None:
        fields["clip_ids"] = args.clips
    if not fields:
        print("nothing to change; pass at least one of --observation --area --evidence --clips "
              "--action --status --result", file=sys.stderr)
        return 2
    with db.connect() as conn:
        out = service.update(conn, args.id, **fields)
    print(_line(out))
    return 0


def cmd_rm(args) -> int:
    with db.connect() as conn:
        if not service.delete(conn, args.id):
            print(f"no lesson {args.id}", file=sys.stderr)
            return 1
    print(f"deleted #{args.id}")
    return 0


def add(sub) -> None:
    desc = "lessons from the numbers: list, add, edit, rm (adopted ones reach every playbook)"
    p = sub.add_parser("feedback", help=desc, description=desc)
    fsub = p.add_subparsers(dest="feedback_command", required=True)

    ls = fsub.add_parser("list", help="newest first")
    ls.add_argument("--status", choices=service.STATUSES)
    ls.add_argument("--area", choices=service.AREAS)
    ls.add_argument("--clip")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    ad = fsub.add_parser("add", help="record a lesson")
    ad.add_argument("observation", help="what the numbers showed")
    ad.add_argument("--area", choices=service.AREAS, default="other")
    ad.add_argument("--evidence", help="the metric and values, e.g. 'swipe-away 62%% on L03 vs 48%% median'")
    ad.add_argument("--clips", nargs="*", help="clip ids; their numbers are copied in now")
    ad.add_argument("--action", help="what to change or test")
    ad.add_argument("--status", choices=service.STATUSES, default="open")
    ad.set_defaults(func=cmd_add)

    ed = fsub.add_parser("edit", help="change any field of a lesson")
    ed.add_argument("id", type=int)
    ed.add_argument("--observation")
    ed.add_argument("--area", choices=service.AREAS)
    ed.add_argument("--evidence")
    ed.add_argument("--clips", nargs="*", help="replaces the linked clips; ones already linked keep their numbers")
    ed.add_argument("--action")
    ed.add_argument("--status", choices=service.STATUSES)
    ed.add_argument("--result")
    ed.set_defaults(func=cmd_edit)

    rm = fsub.add_parser("rm", help="delete a lesson for good")
    rm.add_argument("id", type=int)
    rm.set_defaults(func=cmd_rm)
