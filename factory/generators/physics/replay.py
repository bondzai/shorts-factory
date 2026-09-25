"""A race's trace, and the race drawn again from it with no physics.

The renderers read plain data only — a marble's name, colour and radius, the
style's fields, positions per frame — and draw moving structure from its
clock. So a trace keeps exactly that, and a redraw hands stand-ins to the
same `frames()` with the same caption and ask: the redrawn frame is the
shipped frame, byte for byte (tests/test_trace.py).
"""

from __future__ import annotations

import dataclasses
import itertools
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from ... import audio
from ...series import trace
from .. import fx
from .model import Style
from .render import frames
from .text import closing_ask, overlay


@dataclasses.dataclass
class Marble:
    """What a renderer reads off a ball, without the pymunk body."""

    name: str
    color: tuple[int, int, int]
    radius: float


def style_dict(style: Style) -> dict[str, Any]:
    """The style minus `kinematics` and `rig`, which hold pymunk bodies no
    renderer reads, and minus `mech` when there is none (a race with no
    mechanics writes the trace it always wrote)."""
    return {f.name: getattr(style, f.name) for f in dataclasses.fields(style)
            if f.name not in ("kinematics", "rig") and not (f.name == "mech" and not style.mech)}


def _tuples(value: Any) -> Any:
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


def style_from(data: dict[str, Any]) -> Style:
    # JSON turned every tuple into a list; put them back (PIL wants a colour
    # as a tuple), keeping the style's own lists as lists.
    colours = {"background", "structure", "caption"}
    return Style(**{k: tuple(v) if k in colours else [_tuples(x) for x in v] if isinstance(v, list) else v
                    for k, v in data.items()})


def write(work_dir: Path, *, variant: str, seed: int, fps: int, sim_w: int, sim_h: int,
          rounds: list[dict], captions: list[str | None], ask: bool, outcome) -> Path:
    balls = rounds[0]["balls"]
    arrays = {f"round{i}_positions": np.asarray(r["states"], dtype=np.float64).reshape(len(r["states"]), len(balls), 2)
              for i, r in enumerate(rounds)}
    # One row of radii per round: the final draws its own sizes.
    arrays["radii"] = np.array([[b.radius for b in r["balls"]] for r in rounds], dtype=np.float64)
    arrays["colors"] = np.array([list(b.color) for b in balls], dtype=np.uint8)
    meta = {
        "generator": "physics",
        "variant": variant,
        "seed": seed,
        "fps": fps,
        "sim_w": sim_w,
        "sim_h": sim_h,
        "entrant_ids": [b.name for b in balls],
        "rounds": [
            {"stage": r["style"].stage, "style": style_dict(r["style"]), "segments": r["segments"],
             "winner": r["winner"], "winner_frame": r["winner_frame"],
             "impacts": [[im.t, im.strength, im.index, im.pan] for im in r["impacts"]],
             "overlay": caption}
            for r, caption in zip(rounds, captions)
        ],
        "ask": ask,
        "outcome": outcome.model_dump(mode="json") if outcome is not None else None,
        "engine": fx.engine(),
    }
    return trace.write(work_dir, arrays, meta)


def _round_frames(arrays, meta, n: int) -> Iterator[bytes]:
    fps, sim_w, sim_h = meta["fps"], meta["sim_w"], meta["sim_h"]
    r = meta["rounds"][n]
    balls = [Marble(name, tuple(int(c) for c in colour), float(radius))
             for name, colour, radius in zip(meta["entrant_ids"], arrays["colors"], arrays["radii"][n])]
    states = [[(float(x), float(y)) for x, y in frame] for frame in arrays[f"round{n}_positions"]]
    return frames(states, balls, [_tuples(s) for s in r["segments"]], sim_w, sim_h,
                  overlay=overlay(meta["variant"], sim_w, sim_h, fps, text=r["overlay"]) if r["overlay"] else None,
                  style=style_from(r["style"]),
                  ask=closing_ask(sim_w, sim_h, fps) if meta["ask"] else None,
                  winner_frame=r["winner_frame"], winner=r["winner"],
                  impacts=[audio.Impact(*im) for im in r["impacts"]], fps=fps, engine=meta["engine"])


def redraw(trace_dir: Path) -> Iterator[bytes]:
    """Every frame the render encoded, at sim size, from the trace alone."""
    arrays, meta = trace.read(trace_dir)
    for n in range(len(meta["rounds"])):
        yield from _round_frames(arrays, meta, n)


def redraw_frame(trace_dir: Path, round_index: int, frame: int) -> bytes:
    """One frame. The pygame renderer carries animation state (squash, sparks,
    confetti) from frame to frame, so this draws the round up to `frame`:
    cheap early in a round, a round's worth of drawing at its end."""
    arrays, meta = trace.read(trace_dir)
    return next(itertools.islice(_round_frames(arrays, meta, round_index), frame, None))
