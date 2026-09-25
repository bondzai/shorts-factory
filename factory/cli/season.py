"""Seasons: check the season file, queue its levels, read the table.

    factory season check                  schema, cast, anti-repetition, identity predicates
    factory season plan --levels L01..L03 one make-clip task per ready level
    factory season standings [--after L20] [--recompute]
    factory season status                 levels, their clips, blocked levels, copy path

See docs/08-series-layer.md.
"""

from __future__ import annotations

from .. import channels, db, seasons


def cmd_check(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        out = seasons.check(conn, ch, args.season)
    problems = out["problems"]
    errors = [p for p in problems if p.severity == "error"]
    print(f"{ch.id} season {out['season'] or '?'}: {out['levels']} levels")
    for p in problems:
        print(f"  {p}")
    if out["blocked"]:
        print(f"\nblocked ({len(out['blocked'])}):")
        for level_id, why in out["blocked"]:
            print(f"  {level_id:5} {why}")
    if out["needs_input"]:
        print(f"\nneeds operator input ({len(out['needs_input'])}):")
        for level_id, missing in out["needs_input"]:
            print(f"  {level_id:5} {', '.join(missing)}")
    warnings = len(problems) - len(errors)
    print(f"\n{len(errors)} errors, {warnings} warnings")
    return 1 if errors else 0


def cmd_plan(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        out = seasons.plan(conn, ch, args.levels, season_id=args.season, replan=args.replan)
    for r in out:
        if r["queued"]:
            print(f"  {r['level']:5} queued as task #{r['task_id']}")
        else:
            print(f"  {r['level']:5} refused: {r['reason']}")
    queued = sum(1 for r in out if r["queued"])
    print(f"\n{queued} queued, {len(out) - queued} refused. `factory work` or an agent builds them.")
    return 0 if queued or not out else 1


def cmd_standings(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        out = seasons.standings_view(conn, ch, args.season, after=args.after, recompute=args.recompute)
    head = f"{ch.id} season {out['season']}" + (f" after {out['after']}" if out["after"] else "")
    print(head + (" (recomputed)" if args.recompute else ""))
    if not out["table"]:
        print("  no results yet")
        return 0
    print(f"  {'#':>2}  {'entrant':<16} {'pts':>5} {'wins':>5} {'races':>6}")
    for i, r in enumerate(out["table"], 1):
        print(f"  {i:>2}  {r['name']:<16} {r['points']:>5} {r['wins']:>5} {r['races']:>6}")
    return 0


def cmd_status(args) -> int:
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
        out = seasons.status(conn, ch, args.season)
    print(f"{ch.id} season {out['season']}: {out['title']}")
    print(f"  {'level':5} {'date':10} {'world':16} {'status':12} {'clip':12} {'clip status':14} {'tries':>5}  copy")
    blocked = []
    for lv in out["levels"]:
        if lv["file_status"] == "blocked" and not lv["clip_id"]:
            blocked.append(lv)
        print(f"  {lv['id']:5} {lv['date']:10} {lv['world'][:16]:16} {lv['status']:12} "
              f"{lv['clip_id'] or '-':12} {lv['clip_status'] or '-':14} "
              f"{lv['story_attempts'] if lv['story_attempts'] is not None else '-':>5}  {lv['copy_source'] or '-'}")
        if lv["status"] == "failed" and lv["reason"]:
            print(f"        {lv['reason'][:110]}")
    if blocked:
        print(f"\nblocked ({len(blocked)}):")
        for lv in blocked:
            print(f"  {lv['id']:5} {lv['blocked_on']}")
    print("\n" + ", ".join(f"{k} {v}" for k, v in sorted(out["counts"].items())))
    if out["copy_sources"]:
        total = sum(out["copy_sources"].values())
        rate = ", ".join(f"{k} {v} ({v * 100 // total}%)" for k, v in sorted(out["copy_sources"].items()))
        print(f"copy: {rate}")
    return 0


def add(sub) -> None:
    p = sub.add_parser("season", help="season files: check, plan levels, standings, status",
                       description=__doc__)
    ss = p.add_subparsers(dest="season_command", required=True)

    c = ss.add_parser("check", help="check the season file against the cast and the rules")
    c.add_argument("--season", default=None, help="season id; optional when the channel has one")
    c.set_defaults(func=cmd_check)

    c = ss.add_parser("plan", help="queue make-clip tasks for levels")
    c.add_argument("--levels", required=True, help="L01..L10, or L03,L05")
    c.add_argument("--season", default=None)
    c.add_argument("--replan", action="store_true", help="queue levels already planned again")
    c.set_defaults(func=cmd_plan)

    c = ss.add_parser("standings", help="the season table")
    c.add_argument("--season", default=None)
    c.add_argument("--after", default=None, help="the table after this level, e.g. L20")
    c.add_argument("--recompute", action="store_true", help="rebuild results from approved clips first")
    c.set_defaults(func=cmd_standings)

    c = ss.add_parser("status", help="levels, their clips, blocked levels, copy path")
    c.add_argument("--season", default=None)
    c.set_defaults(func=cmd_status)
