"""Out of the door, and what came back: publishing, the YouTube
connection, the numbers each clip earned, and what the agents cost.
"""

from __future__ import annotations

from .. import analytics, channels, db, llm, pipeline, settings
from ..publish import youtube as yt


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


def cmd_youtube(args) -> int:
    """Connect a channel to YouTube, say what is connected, or forget a token."""
    with db.connect() as conn:
        ch = channels.resolve(conn, args.channel)
    driver = yt.YouTubePublisher(ch)
    if args.action == "connect":
        print(f"connecting {ch.id} — sign in as the account that owns this channel, "
              f"and pick the right channel on the 'Choose your account or a brand account' screen")
        try:
            who = driver.connect(open_browser=not args.no_browser, browser=args.browser)
        except Exception as exc:
            print(f"not connected: {exc}")
            return 1
        print(f"connected as {who['title']} ({who['id']})"
              + (f" · {who['subscribers']} subscribers" if who.get("subscribers") is not None else ""))
        print(f"token: {driver.token_path.relative_to(settings.ROOT)} (gitignored, this channel only)")
        return 0
    if args.action == "disconnect":
        print("forgot the token" if driver.disconnect() else "nothing to forget")
        print("the grant itself lives in the Google account: revoke it at "
              "https://myaccount.google.com/permissions")
        return 0
    status = driver.status()
    print(f"channel      {ch.id} ({ch.name}), driver {ch.driver}")
    print(f"client id    {'client_secrets.json found' if status['client_secrets'] else 'MISSING client_secrets.json'}")
    print(f"connected    {'yes' if status['connected'] else 'no'}")
    if status.get("account"):
        a = status["account"]
        print(f"as           {a['title']} ({a['id']})" + (f" · {a['videos']} videos" if a.get("videos") is not None else ""))
    if status.get("error"):
        print(f"error        {status['error']}")
    print(f"uploads      {status['privacy']}; about {status['uploads_per_day']} a day within YouTube's quota")
    return 0 if status["connected"] else 1


def cmd_cost(args) -> int:
    rows = analytics.cost_by_agent(days=args.days, channel_id=args.channel)
    print(f"{'agent':<10} {'model':<20} {'calls':>6} {'in':>9} {'out':>8} "
          f"{'$/call':>9} {'total':>9}")
    total = 0.0
    for row in rows:
        total += row["cost_usd"]
        mark = " ~" if row["estimated"] else ""
        print(
            f"{row['agent']:<10} {row['model']:<20} {row['calls']:>6} "
            f"{row['input_tokens']:>9} {row['output_tokens']:>8} "
            f"{row['usd_per_call']:>9.5f} {row['cost_usd']:>9.4f}{mark}"
        )
    if not rows:
        print("\nno agent calls logged yet")
        return 0
    print(f"\ntotal over {args.days} day(s): ${total:.4f}")
    print("\nconfigured models:")
    for agent in ("idea", "metadata", "qc", "analyst"):
        print(f"  {agent:<10} {llm.model_for(agent)}")
    if any(r["estimated"] for r in rows):
        print("\n~ = model not in [llm.pricing]; billed at the default rate")
    return 0


def add(sub) -> None:
    p = sub.add_parser("publish", help="publish approved clips", description="publish approved clips")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_publish)

    sub.add_parser("pull-metrics", help="refresh metrics from the platform", description="refresh metrics from the platform").set_defaults(func=cmd_pull_metrics)

    p = sub.add_parser("set-metrics", help="enter metrics by hand (manual driver)", description="enter metrics by hand (manual driver)")
    p.add_argument("clip_id")
    p.add_argument("--views", type=int, required=True)
    p.add_argument("--avg-view-pct", type=float, required=True, dest="avg_view_pct")
    p.add_argument("--swipe-away-pct", type=float, required=True, dest="swipe_away_pct")
    p.add_argument("--likes", type=int, default=0)
    p.set_defaults(func=cmd_set_metrics)

    p = sub.add_parser("digest", help="Analyst digest over published clips", description="Analyst digest over published clips")
    p.add_argument("--apply-rules", action="store_true")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("youtube", help="connect a channel to YouTube, check it, or forget the token",
                       description="connect a channel to YouTube, check it, or forget the token")
    p.add_argument("action", nargs="?", default="status", choices=["status", "connect", "disconnect"])
    p.add_argument("--channel", help="which channel (default: the first active one)")
    p.add_argument("--browser", choices=["chrome", "safari", "firefox", "edge"],
                   help="open the sign-in in a private window of this browser, so Google asks "
                        "which account to use instead of assuming the one already signed in")
    p.add_argument("--no-browser", action="store_true",
                   help="print the sign-in URL instead of opening a browser \u2014 paste it into the "
                        "browser profile signed in to the channel's account")
    p.set_defaults(func=cmd_youtube)

    p = sub.add_parser("cost", help="spend per agent and per model, from the event log", description="spend per agent and per model, from the event log")
    p.add_argument("--days", type=int, default=7)
    p.set_defaults(func=cmd_cost)
