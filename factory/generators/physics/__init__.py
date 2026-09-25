"""Marble races and funnel drops: deterministic 2D physics, one clip at a time.

Two variants, both fully determined by the seed: `marble_race`, where a few
marbles race a stage to a finish line, and `funnel_drop`, where dozens of
small balls pour through a funnel.

The module this replaced had grown to 1,600 lines holding five jobs at once.
They are now one module each, and each may only import the ones below it:

    model       constants, the style bag, a marble        (imports nothing here)
    stages      the eleven hand-built stage builders      → model
    registry    one Stage entry each, and the lookups     → stages
                (and one Mechanic entry per level `section`)
    addons      spinning bars, the finish throat          → registry
    transform   a round's mirror image                    → model
    build       walls, stage, add-ons, marbles            → addons, transform
                (the round's rig: ../mechanics.py, docs/10)
    simulate    the physics, and the retry loop           → build
    text        captions, the closing ask, the account    → registry
    render_pil  the original drawing
    render_pgm  the same race with motion on every object
    render_mech what the mechanics recorded, for both
    render      which of the two, by `render.engine`
    outcome     placements, lead changes, events          → registry
    replay      the trace, and a redraw from it           → render, text
    sandbox     the generator the factory registers       → all of the above

Impacts are detected from per-frame velocity changes rather than pymunk's
collision callbacks, because the callback API moved between pymunk 6 and 7
and this only needs to know that something hit something hard.

What other code may use is re-exported here, so `from .generators import
physics` keeps working and nothing outside reaches into a submodule.
"""

from .addons import (FINISH_GATE_CHANCE, GATE_GAP, GATE_GAP_COMPOSED, GATE_HEIGHT,  # noqa: F401
                     GATE_RISE_COMPOSED, GAUNTLET_OMEGA, MARBLE_SPREAD, TWIN_CAP, TWIN_CENTRE,
                     TWIN_GAP, TWIN_HALF, TWIN_RISE, TWIN_TILT, add_finish_gate, add_spinners)
from .build import build_funnel, build_race  # noqa: F401
from .model import (BACKGROUND, CLOSE_RACE_S, FINAL_CAPTION, IMPACT_DV, MAX_SPEED,  # noqa: F401
                    PALETTES, POST_WIN_MAX_S, POST_WIN_S, RACE_COLORS, RACE_GRAVITY,
                    ROCK_AMPLITUDE, STALL_SPEED, STRUCTURE, SUBSTEPS, TIP_GAP, TRAP_SWING, Ball,
                    Stalled, Style, make_ball, parse_hex, pick, seconds, structure_for, trap_angle)
from .registry import (BUILDERS, GATE_STAGES, LIVE_STAGES, SPINNER_ROWS, SPINNER_STAGES,  # noqa: F401
                       STAGE_BLURB, STAGE_BY_ID, STAGE_GRAVITY, STAGE_NOUN, STAGE_SPECS, STAGES,
                       TWIN_STAGES, WHEEL_STAGES, Stage)
from .render import frames  # noqa: F401
from .render_pil import frames_pil  # noqa: F401
from .render_pygame import frames_pygame  # noqa: F401
from .sandbox import (STORY_STRIDE, PhysicsSandbox, StoryUnsatisfiable, choose_story, generate,  # noqa: F401
                      race_outcome, race_rounds, story_seed)
from .build import TRAITS, known_traits  # noqa: F401
from .replay import redraw, redraw_frame  # noqa: F401
from .simulate import run_round, simulate  # noqa: F401
from .text import closing_ask, default_hook, overlay, stage_text  # noqa: F401
from ..base import register

register(PhysicsSandbox())
