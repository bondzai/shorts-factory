"""Which renderer draws a clip: `render.engine` in config."""

from __future__ import annotations

from typing import Iterator

from .. import fx
from .render_pil import frames_pil
from .render_pygame import frames_pygame

def frames(states, balls, segments, sim_w, sim_h, overlay=None, style=None,
           winner_frame=None, winner=None, ask=None, impacts=None, fps=30, engine=None,
) -> Iterator[bytes]:
    """One frame renderer or the other, by `render.engine` (or `engine`, which
    a redraw passes so a trace is drawn the way it was shipped). Same inputs,
    same physics; pygame adds motion to every object."""

    if (engine or fx.engine()) == "pygame":
        yield from frames_pygame(states, balls, segments, sim_w, sim_h, overlay=overlay, style=style,
                                       winner_frame=winner_frame, winner=winner, ask=ask,
                                       impacts=impacts or [], fps=fps)
        return
    yield from frames_pil(states, balls, segments, sim_w, sim_h, overlay=overlay, style=style,
                                winner_frame=winner_frame, winner=winner, ask=ask)
