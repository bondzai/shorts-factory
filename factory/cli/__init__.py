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

One module per thing you are doing. Each owns both halves of its commands —
what the flags are, and what they do — so a command is added or changed in
one place.
"""

from __future__ import annotations

import argparse
import sys

from . import channels, make, ops, publish, review, setup

#: In the order `factory --help` should read: set it up, then the loop,
#: then the machinery around it.
GROUPS = (setup, channels, make, review, publish, ops)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description=__doc__)
    parser.add_argument(
        "--channel", default=None,
        help="channel id; optional while only one channel is active",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for group in GROUPS:
        group.add(sub)
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
