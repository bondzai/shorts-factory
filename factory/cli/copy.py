"""Season copy on an existing level clip: `factory copy --clip <id>`.

Re-runs the copy stage (docs/08 §4) and applies it the way a person would:
the title through `retitle`, so the old one and its numbers are kept; the
description through `redescribe`; the pinned comment. It prints the plan's
hint, what was chosen and the template's fallback side by side, which is the
comparison docs/08 §8 step 7 asks for. `--burn-hook` re-renders the opening
caption through `rehook` — the one path that may change pixels.
"""

from __future__ import annotations

import sys

from .. import channels, db

LABELS = {"title": "title", "hook": "hook", "pin": "pin", "desc_line1": "desc line 1"}


def _cell(text: str | None, width: int) -> str:
    text = (text or "-").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def cmd_copy(args) -> int:
    from ..pipeline import rehook
    from ..series import copywriter

    with db.connect() as conn:
        row = db.get(conn, args.clip)
        if row is None:
            print(f"no clip {args.clip}", file=sys.stderr)
            return 1
        if not row["level_id"]:
            print(f"{args.clip} is not a season level clip; `factory retitle` is for those", file=sys.stderr)
            return 2
        ch = channels.get(conn, row["channel_id"])
        result = copywriter.write(conn, args.clip, brain=args.brain, rules=ch.rules())
        out = copywriter.apply(conn, result, by="human")
        hints = result.setting.level.copy_ if result.setting.level else None
        w = 44
        print(f"{args.clip}  level {result.setting.level_id}  copy: {result.source}")
        print(f"  {'':12} {'plan hint':{w}} {'chosen':{w}} {'fallback':{w}}")
        for f, label in LABELS.items():
            hint = getattr(hints, "desc" if f == "desc_line1" else f, None) if hints else None
            chosen = result.chosen.text.get(f)
            tag = result.chosen.source.get(f, "")
            print(f"  {label:12} {_cell(hint, w):{w}} {_cell(chosen, w - 11) + ' [' + tag + ']':{w}} "
                  f"{_cell(result.fallback.get(f), w)}")
        print(f"\n  description:\n    " + result.metadata.description.replace("\n", "\n    "))
        for r in result.chosen.rejected:
            print(f"  rejected {r['field']}: {r['text']!r} - {r['why']}")
        print(f"\n  changed: {', '.join(out['changed']) or 'nothing'}")
        if args.burn_hook:
            hook = result.chosen.text.get("hook")
            if not hook:
                print("  no hook chosen; the render's caption stays", file=sys.stderr)
                return 1
            outcome = rehook(conn, args.clip, hook, by="human")
            print(f"  {outcome.clip_id} {outcome.status}: {outcome.detail}")
            return 0 if outcome.status != "failed" else 1
    return 0


def add(sub) -> None:
    desc = "re-run season copy on a level clip and apply it (title history kept)"
    p = sub.add_parser("copy", help=desc, description=desc)
    p.add_argument("--clip", required=True)
    p.add_argument("--brain", choices=("local", "template"), default=None,
                   help="local asks the copy brain and falls back; template never asks "
                        "(default: [series] copy_source)")
    p.add_argument("--burn-hook", action="store_true",
                   help="re-render the opening caption with the chosen hook (through rehook)")
    p.set_defaults(func=cmd_copy)
