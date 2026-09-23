"""Getting it running, and asking it what it is set to.

None of these touch a clip: they make the database, check the machine, show
what is configured and draw the channel art.
"""

from __future__ import annotations

import json
import shutil

from PIL import Image

from .. import brand, channels, db, generators, llm, playbooks, settings


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
    # Per agent, because each can run on its own provider now. Not fatal: the
    # external path (Codex or Claude Code over MCP) needs none of this.
    for agent, r in llm.readiness().items():
        print(f"{agent:9s} {r.get('provider', '?')}/{r.get('model', '?')}  {'ok' if r['ok'] else 'not ready — ' + str(r['why'])}")
    if not llm.has_credentials():
        print("          built-in agents are not all ready; playbooks over MCP still work")
    with db.connect() as conn:
        found = channels.all_channels(conn)
    print(f"channels  {len(found)} ({', '.join(c.id for c in found) or 'none — run factory init'})")
    return 0 if ok else 1


def cmd_generators(args) -> int:
    for name, gen in generators.all_generators().items():
        flag = "ready" if getattr(gen, "ready", True) else "stub"
        print(f"{name:15} [{flag}] variants: {', '.join(gen.variants)}")
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


def cmd_config(args) -> int:
    cfg = settings.load()
    if args.action == "list":
        for f in settings.SCHEMA:
            key = (f["section"], f["key"])
            value = cfg.raw.get(f["section"], {}).get(f["key"])
            mark = "  (override)" if key in cfg.overrides else ""
            print(f"{f['section']}.{f['key']:26s} {value!r}{mark}")
        return 0
    section, _, key = args.name.partition(".")
    field = next((f for f in settings.SCHEMA if f["section"] == section and f["key"] == key), None)
    if field is None:
        print(f"no setting {args.name}; run `factory config list`", file=sys.stderr)
        return 2
    with db.connect() as conn:
        if args.action == "reset":
            db.clear_override(conn, section, key)
            print(f"{args.name} back to config.toml")
        else:
            try:
                value = settings.coerce(field, args.value)
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 2
            db.set_override(conn, section, key, value)
            print(f"{args.name} = {value!r}")
    settings.invalidate()
    return 0


def cmd_brains(args) -> int:
    if args.test:
        result = llm.test_provider(args.test, args.model)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    for p in llm.providers():
        key = "no key needed" if not p.api_key_env else (f"{p.api_key_env} set" if p.key_present() else f"{p.api_key_env} MISSING")
        print(f"{p.id:12s} {p.kind:9s} {p.base_url or '-':52s} {key}{'  no vision' if not p.vision else ''}")
    print()
    for agent, r in llm.readiness().items():
        print(f"{agent:9s} {r.get('provider', '?')}/{r.get('model', '?'):28s} {'ok' if r['ok'] else 'NOT READY: ' + str(r['why'])}")
    return 0


def cmd_brand(args) -> int:
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


def cmd_playbook(args) -> int:
    if args.name is None:
        for name in playbooks.available():
            print(name)
        return 0
    print(playbooks.render(args.name, args.channel))
    return 0


def add(sub) -> None:
    sub.add_parser("init", help="create the database, migrate, seed a channel", description="create the database, migrate, seed a channel").set_defaults(func=cmd_init)
    sub.add_parser("doctor", help="check ffmpeg, dependencies, credentials", description="check ffmpeg, dependencies, credentials").set_defaults(func=cmd_doctor)
    sub.add_parser("generators", help="list generator modules", description="list generator modules").set_defaults(func=cmd_generators)
    sub.add_parser("status", help="counts by stage per channel", description="counts by stage per channel").set_defaults(func=cmd_status)

    p = sub.add_parser("playbook", help="print a reusable agent prompt, filled in from the live database", description="print a reusable agent prompt, filled in from the live database")
    p.add_argument("name", nargs="?", help="playbook name; omit to list them")
    p.add_argument("--channel", default=None)
    p.set_defaults(func=cmd_playbook)

    p = sub.add_parser("config", help="list or change the settings the page can change", description="list or change the settings the page can change")
    p.add_argument("action", choices=["list", "set", "reset"])
    p.add_argument("name", nargs="?", help="section.key, e.g. qc.max_sameness")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("brains", help="which model each built-in agent runs on, and whether it can", description="which model each built-in agent runs on, and whether it can")
    p.add_argument("--test", metavar="PROVIDER", help="one-word round trip through a provider")
    p.add_argument("--model", default=None)
    p.set_defaults(func=cmd_brains)

    p = sub.add_parser("brand", help="draw the channel avatar and banner", description="draw the channel avatar and banner")
    p.add_argument("--title", default="GRAVITY LAB")
    p.add_argument("--tagline", default="no talking  \u00b7  sound on")
    p.set_defaults(func=cmd_brand)
