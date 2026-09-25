"""World 10, the Christmas Grand Final (Season 0, L91-L100): the other worlds, put together.

Almost nothing here is new mechanism. A quarterfinal is an earlier world's
stage raced again (L91 World 1's zigzag, L92 World 4's final maze, L93 World
6's dice duel); a semifinal is a stage stacked from three worlds' sections,
each doing what it did in its own world; the Grand Final runs three such
stages as its three rounds. What this module adds is the wiring, in one
place: **`gauntlet`** looks at what a stage built and switches on each
world's mechanism for it —

  magnets        World 3's flip: pull, then a jolt and a push from `flip_at`
  colour gates   World 9: the first lights one seeded colour (the rest wait),
                 the second cycles every colour a second
  panels         World 2: each trapdoor panel on its own seeded cycle,
                 shut for the first GRACE_S
  dice gates     World 6: a die per gate, rolled as the leader nears it
  bumpers        World 4: some of them are pumpkins that roll when hit
  fog            World 4: the lights out over part of the course (knob)
  repel          World 8: every marble pushes every other apart (knob)

— and the ice (World 5) and the maze's dead ends (World 4) are geometry,
built by their sections. Every choice those mechanisms make comes from
`rig.rng` or from where the race is, never from who a marble is (docs/08
rule 2.4): the modules they come from say how.

Two levels are not races, and two things are new for them:

- **L99, the champion's lap**: one marble through the final's three tracks
  with the season standings drawn on screen (`rig.effect("board")`). The
  rows are the standings table as it stood when the level was planned
  (`planning.plan` fills `mechanics.standings`); with none filled in, no
  board is drawn — the render never makes up a table. The trapdoors stay
  shut: a lap is a lap.
- **L100, the Season One teaser**: a track under construction — the
  `scaffold` section's ramps are drawn as blueprint lines and are built,
  one by one, in construction yellow, as the field comes down to them — and
  a new marble's silhouette by the line at the end (a prop with no body,
  never an entrant). The six regulars roll through it; the level is marked
  `scored: false`, so its result is not counted in the standings.
"""

from __future__ import annotations

from ... import stagekit
from ...mechanics import FINISH_Y, _seg_dist, rig_of
from ...stagekit import dice_record
from . import colour_gates as w9
from . import dice as w6
from . import haunted as w4
from . import polarity as w3
from . import repel as w8
from . import trapdoor as w2

# The trapdoor's share of its cycle open, in a gauntlet. A semifinal is a
# duel: a panel open as often as World 2's takes one of the two out and the
# other walks home alone (no race left to watch).
TRAP_SHARE = 0.30
FLIP_AT = 0.35  # the magnet band sits high on the semifinal track
# The construction yellow of a ramp once it is built, and how far above a
# ramp's high end the leader is when it gets built.
BUILT = (240, 190, 40)
# Just in time: at 150 px the first two ramps were built within a second of
# the start and the blueprints were barely on screen.
BUILD_AHEAD = 80.0
SCAFFOLD_STEP = (80.0, 100.0)  # px of band per ramp: more, shorter ramps than the kit's 95-130
# Steeper than the kit's ramps (0.37-0.44, raced at -600 on zigzag): on a
# stage whose pegs set the pace (-30 to -90) a marble dropped into the
# corner at a ramp's high end sat there.
SCAFFOLD_SLOPE = (0.55, 0.62)
SILHOUETTE_FROM = 0.85  # race fraction: the new marble shows up near the end


# --- the gauntlet: every world's mechanism a stage has room for ----------------------------------

def gauntlet(rig, space, style, balls, w, h, *, traps: bool = True, repel: float | None = None) -> list[str]:
    """Switch on each world's mechanism for what this stage built. Returns
    the worlds' mechanisms it found (for tests and docs/06). `traps=False`
    keeps every trapdoor panel shut (the champion's lap); `repel` is the
    push's strength when the level's knob `repel` sets none (None: no push)."""
    found = []
    if style.magnets:
        w3.install(rig, style, {"band": w3.flip_rule(rig, float(rig.knob("flip_at", FLIP_AT)),
                                                      float(rig.knob("push", w3.FLIP_PUSH)))})
        found.append("magnets")
    gates = w9.gates_of(rig)
    if gates:
        if rig.knob("first_gate", "random") == "cycle":
            w9.cycling_colour_gate(rig, space, style, balls, w, h, gate=0)
        else:
            w9.random_colour_gate(rig, space, style, balls, w, h, gate=0, hold=w9.HOLD_SHORT_S)
        for k in range(1, len(gates)):
            w9.cycling_colour_gate(rig, space, style, balls, w, h, gate=k)
        found.append("colour_gates")
    coffin = getattr(rig, "coffin", None)
    haunted = bool(w4.maze_of(rig)) and coffin is not None and traps
    if haunted:
        # World 4's final maze, as L37 raced it: pumpkins on the first join,
        # the fog over the middle, a web, the coffin on its own cycle (knobs
        # `open_share`, `fog_from`, `fog_to`, `fork`).
        w4.haunted_final(rig, space, style, balls, w, h)
        found += ["maze", "pumpkins", "fog", "web", "coffin"]
    panels = [p for p in w2.panels_of(rig) if not (haunted and p is coffin)]
    if panels:
        share = float(rig.knob("open_share", TRAP_SHARE)) if traps else 0.0
        for p in panels:
            if share > 0:
                p.opener = w2.cycling(rig.rng.uniform(2.6, 3.2), share, rig.rng.random(), after=w2.GRACE_S)
            else:
                p.opener = lambda f: False
        found.append("trapdoors" if share > 0 else "trapdoors_shut")
    dice_gates = dice_record(style)["gates"]
    if dice_gates:
        for k in range(len(dice_gates)):
            w6.gate(rig, space, style, k)
        found.append("dice")
    if not haunted and style.circles and rig.knob("pumpkins", 0):
        w4.rolling_pumpkins(rig, space, style, balls, w, h)
        found.append("pumpkins")
    if not haunted and rig.knob("fog_from") is not None:
        w4.fog(rig, start=float(rig.knob("fog_from")), end=float(rig.knob("fog_to", 0.8)))
        found.append("fog")
    strength = rig.knob("repel", repel)
    if strength and len(balls) > 1:
        w8.repel(rig, float(strength))
        found.append("repel")
    if w4.maze_of(rig) and not haunted:
        found.append("maze")
    rig.w10_found = found
    return found


def magnets_ice_gates(rig, space, style, balls, w, h):
    """L95: magnets that flip, ice, and colour gates, on one track."""
    found = gauntlet(rig, space, style, balls, w, h)
    if not {"magnets", "colour_gates"} <= set(found):
        raise ValueError("gauntlet-magnets-ice-gates needs a stage with magnets and a colour gate (magnetgates)")


def trapdoors_repulsion_dice(rig, space, style, balls, w, h):
    """L96: trapdoor panels, the push between marbles, and dice gates."""
    found = gauntlet(rig, space, style, balls, w, h, repel=w8.STRENGTH)
    if not {"trapdoors", "dice"} <= set(found):
        raise ValueError("gauntlet-trapdoors-repulsion-dice needs a stage with a trapdoor and a dice gate (trapdice)")


def grand_final(rig, space, style, balls, w, h):
    """L98: every round is a gauntlet — whatever this round's stage built is
    switched on (the level's `round_params` pick the stages)."""
    if not gauntlet(rig, space, style, balls, w, h):
        raise ValueError("grand-final-composite found no world's mechanism on this stage")


# --- the champion's lap ----------------------------------------------------------------------

BOARD_ROWS = 6


def standings_rows(value) -> list[dict]:
    """The board's rows from `mechanics.standings` as planning filled it in:
    a list of {name, points, color}. Anything else (the level's marker
    "at_plan" left unfilled, a QA run) is no rows."""
    if not isinstance(value, list):
        return []
    rows = []
    for r in value[:BOARD_ROWS]:
        if isinstance(r, dict) and r.get("name") is not None:
            colour = r.get("color")
            rows.append({"name": str(r["name"]), "points": r.get("points", 0),
                         "color": list(colour) if isinstance(colour, (list, tuple)) else None})
    return rows


def champion_lap(rig, space, style, balls, w, h):
    """L99: the gauntlet for one marble, trapdoors shut, and the standings
    board under the line for the whole lap."""
    gauntlet(rig, space, style, balls, w, h, traps=False)
    rows = standings_rows(rig.knob("standings"))
    if rows:
        rig.effect("board", rows=rows, at=(w / 2, FINISH_Y * 0.46), title="SEASON STANDINGS")


# --- the Season One teaser -------------------------------------------------------------------

def scaffold(space, w, top, bottom, rng, style):
    """Zigzag ramps (the kit's `ramps`) that are not built yet: each is a
    door, drawn as a faint blueprint line and passable, until the leader
    comes down to within BUILD_AHEAD of its high end; then it is built for
    good (solid, construction yellow, a `built` event) — unless a marble is
    touching it, when it waits a frame, so a ramp is never built through
    one. Only where the race is builds a ramp, never who is leading."""
    rig = rig_of(style)
    height = top - bottom
    count = max(2, int(height // rng.uniform(*SCAFFOLD_STEP)))
    slope = rng.uniform(*SCAFFOLD_SLOPE)
    step = height / count
    span = min(step / slope, w - 90.0)
    mirrored = rng.random() < 0.5
    thick = style.thickness / 2
    ramps = getattr(rig, "scaffold", None)
    if ramps is None:
        ramps = rig.scaffold = []
    for i in range(count):
        y = top - i * step
        starts_left = (i % 2 == 0) != mirrored
        a, b = ((26.0, y), (26.0 + span, y - step)) if starts_left else ((w - 26.0, y), (w - 26.0 - span, y - step))
        k = len(ramps)
        state = {"built": False, "a": a, "b": b}
        ramps.append(state)

        def built(f, state=state, k=k):
            if state["built"]:
                return True
            racing = [i for i in range(len(f.names)) if f.alive[i] and f.names[i] not in f.finished]
            if not racing or min(f.positions[i][1] for i in racing) > max(state["a"][1], state["b"][1]) + BUILD_AHEAD:
                return False
            clear = all(_seg_dist(f.positions[i], state["a"], state["b"]) > f.rig.balls[i].radius + thick + 4.0
                        for i in racing)
            if clear:
                state["built"] = True
                f.rig.emit("built", None, ramp=k)
            return state["built"]

        rig.clock(f"scaffold{k}", built)
        rig.door(space, a, b, closed=f"scaffold{k}", color=BUILT, thickness=thick)
        rig.effect("sketch", clock=f"scaffold{k}", a=a, b=b)
    return []


def season_one_teaser(rig, space, style, balls, w, h):
    """L100: the track under construction (the scaffold section does it)
    and, from SILHOUETTE_FROM of the way down, a new marble's silhouette
    beside the line: a picture with no body, never an entrant."""
    if not getattr(rig, "scaffold", None):
        raise ValueError("season-one-teaser needs a stage with the scaffold section (construction)")
    r = w * 0.05
    start = float(rig.knob("silhouette_from", SILHOUETTE_FROM))
    state: dict = {"at": None}

    def newcomer(f):
        # Placed once, under the line a few marbles' widths from where the
        # leader is when the race is SILHOUETTE_FROM of the way down, on the
        # side toward the middle: the finish is filmed tight on the leader,
        # and a silhouette in a far corner was never in frame. Where the
        # leader is, not who: the silhouette has no body and changes nothing.
        if state["at"] is None and f.progress >= start and f.leader is not None:
            x = f.positions[f.leader][0]
            side = 1.0 if x < w / 2 else -1.0
            x = min(max(x + side * r * 3.2, r + 14.0), w - r - 14.0)
            state["at"] = [round(x, 1), round(FINISH_Y * 0.42, 1)]
        return state["at"]

    rig.clock("newcomer", newcomer)
    rig.effect("prop", clock="newcomer", track=True, radius=r, color=[14, 14, 18], look="silhouette")


# --- registration ------------------------------------------------------------------------------

SECTIONS = {"scaffold": scaffold}
SECTION_WORDS = {"scaffold": "ramps still being built"}
stagekit.SECTIONS.update(SECTIONS)
stagekit.SECTION_WORDS.update(SECTION_WORDS)

# The semifinal and final tracks, as sections: (id, parts). Registered in
# physics/registry.py beside every other trial stage.
#
# magnetgates: the ice is the gate's arms (World 9's `icegate`, World 5's
# ice). A band of World 5's ice ramps over the gate parked marbles on it (14
# and 12 of 87 and 83, the gate squeezing the ramps flat, as L90 found).
# trapdice: the dice gate first, then the panel. With the panel on top a duel
# was past it before World 2's GRACE_S and it never opened under anyone.
MAGNETGATES = (("pegs", 0.5), ("magnets", 1.2), ("icegate", 1.5), ("pegs", 0.6))
TRAPDICE = (("dicegate", 2.0), ("trap1", 1.1), ("pegs", 0.6))
# construction: pegs under the scaffold, not a funnel: six marbles queued in
# the funnel's throat (27 of 183 parked).
CONSTRUCTION = (("pegs", 0.8), ("scaffold", 1.6), ("pegs", 0.8))
