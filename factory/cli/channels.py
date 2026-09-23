"""The channels themselves: list them, add one, change one."""

from __future__ import annotations

from .. import channels, db


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


def add(sub) -> None:
    parser = sub.add_parser("channels", help="add, list and edit channels", description="add, list and edit channels")
    channel_sub = parser.add_subparsers(dest="channel_command", required=True)
    channel_sub.add_parser("list").set_defaults(func=cmd_channels_list)

    p = channel_sub.add_parser("add", help="create a channel", description="create a channel")
    p.add_argument("name")
    p.add_argument("--id", default=None, help="internal id; defaults to a slug of the name")
    p.add_argument("--handle", default=None)
    p.add_argument("--platform", default="youtube")
    p.add_argument("--driver", default=None, choices=["manual", "youtube"])
    p.add_argument("--variant", action="append", help="generator/variant; repeatable")
    p.add_argument("--cadence", type=int, default=1)
    p.set_defaults(func=cmd_channels_add)

    p = channel_sub.add_parser("edit", help="change a channel", description="change a channel")
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
