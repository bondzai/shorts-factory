"""One entry per stage, and every lookup derived from it.

Adding a stage is adding a line here. The dictionaries below exist because
the web API, the task validator and the tests read them; they are views of
STAGE_SPECS, never a second source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import stagekit
from . import stages
<<<<<<< HEAD
from .worlds import polarity
=======
from .worlds import dice
>>>>>>> wp7-w6

@dataclass(frozen=True)
class Stage:
    """Everything the factory knows about one stage, in one place.

    Before this, a stage lived in seven dictionaries and a describe table,
    and adding one meant editing all of them and hoping a test caught the
    one you missed. Now a stage is one entry; the old names below are
    derived from the list and stay only because other code reads them.

    weight   share of random picks among live stages. 0 = trial: a trial
             stage renders when a task names it, and is never picked at
             random. `factory stage-qa` is what promotes a stage.
    gravity  pace; tuned so the median finish lands mid-window.
    parts    for a composed stage, the sections it stacks (see stagekit).
    """

    id: str
    build: Any
    gravity: float
    noun: str
    blurb: str
    describe: Any
    weight: float = 0.0
    spinners: tuple[int, int] | None = None
    spinner_rows: tuple[float, ...] = ()
    wheel: int = 0
    gate: bool = False
    twin: bool = False  # the gate forks into two exits instead of one throat
    parts: tuple = ()

    @property
    def live(self) -> bool:
        return self.weight > 0

    @property
    def composed(self) -> bool:
        return bool(self.parts)


def obstacles(style, segments) -> int:
    return len(style.circles) or len(segments)


def composed(id_, parts, *, gravity, noun, blurb, weight=0.0, gate=False, twin=False):
    """A stage stacked from stagekit sections. With the finish throat the
    stack stops above the throat's mouth (0.31 h) with a marble's room to
    spare — the drums and sieve stages learned what a section overlapping
    the throat does."""
    build = stagekit.compose(list(parts), bottom_frac=0.36 if gate else 0.20)
    return Stage(
        id=id_, build=build, gravity=gravity, noun=noun, blurb=blurb,
        describe=lambda style, segments, _p=tuple(parts): stagekit.describe_parts(_p),
        weight=weight, gate=gate, twin=twin, parts=tuple(parts),
    )


STAGE_SPECS: list[Stage] = [
    Stage("zigzag", stages.build_zigzag, -600.0, "ramps", "ramps — fast, the classic",
          lambda s, g: f"a {obstacles(s, g)}-ramp zigzag stage", weight=0.16),
    Stage("pegboard", stages.build_pegboard, -110.0, "pegs", "pegs — a slow rattle down a Galton board",
          lambda s, g: f"a pegboard of {obstacles(s, g)} pegs", weight=0.12),
    Stage("bumpers", stages.build_bumpers, -95.0, "bumpers", "bumpers and spinning bars — the busiest frame",
          lambda s, g: f"a field of {obstacles(s, g)} bumpers", weight=0.14,
          spinners=(3, 4), spinner_rows=(0.26, 0.40, 0.54, 0.68), gate=True),
    Stage("funnels", stages.build_funnels, -45.0, "funnels", "stacked funnels — every throat is a bottleneck",
          lambda s, g: f"{obstacles(s, g) // 2} stacked funnels", weight=0.09),
    # No bar at 0.70, where the funnel dumps the field onto it: it juggled
    # the field for a whole clip.
    Stage("gauntlet", stages.build_gauntlet, -55.0, "spinners", "a lane of spinning bars — nothing else in the way",
          lambda s, g: "a narrow gauntlet", weight=0.09,
          spinners=(4, 5), spinner_rows=(0.20, 0.30, 0.40, 0.50, 0.60), gate=True),
    Stage("cascade", stages.build_cascade, -200.0, "chutes", "chutes that split and rejoin — the marbles keep swapping sides",
          lambda s, g: f"a cascade of {obstacles(s, g)} chutes", weight=0.03),
    Stage("pinwheel", stages.build_pinwheel, -40.0, "arms", "one big four-armed wheel in the middle, pegs around it",
          lambda s, g: f"a four-armed pinwheel among {obstacles(s, g)} pegs", weight=0.09, wheel=2),
    Stage("sieve", stages.build_sieve, -60.0, "bars", "rows of short tilted bars with gaps — a sieve the marbles fall through",
          lambda s, g: f"a sieve of {obstacles(s, g)} tilted bars", weight=0.09, gate=True),
    Stage("pachinko", stages.build_pachinko, -70.0, "pegs", "pegs on arcs around a central bumper, like a pachinko board",
          lambda s, g: f"a pachinko board of {obstacles(s, g)} pegs", weight=0.07),
    Stage("rockers", stages.build_rockers, -150.0, "planks", "planks that rock on a pivot — tip one way, then the other",
          lambda s, g: f"{len(s.rockers)} rocking planks", weight=0.06),
    Stage("drums", stages.build_drums, -40.0, "drums", "big spinning drums that carry a marble sideways before it drops",
          lambda s, g: f"{len(s.drums)} spinning drums", weight=0.06, gate=True),
    # --- composed from stagekit sections. Trial (weight 0) until stage-qa passes them.
    # COMPOSED-STAGES-BEGIN
    # Gravity from `factory stage-qa --calibrate`; weight 0.05 each once the
    # stage passed every gate on 48 fresh seeds (2026-09-23, docs/06). arcade
    # stays trial: its lead changed 1.1 times a race against a gate of 1.5.
    composed("arcade", [("bumpers", 1.1), ("spinners", 1.2), ("pegs", 1.0)], gravity=-30.0, noun="bumpers",
              blurb="bumpers, then a row of spinning bars, then pegs", gate=True),
    composed("plinko", [("pegs", 1.0), ("wheel", 1.6), ("pegs", 1.0)], gravity=-31.0, noun="pegs",
              blurb="pegs, a big four-armed wheel, then more pegs", gate=True, weight=0.05),
    composed("switchback", [("ramps", 1.2), ("belts", 1.0), ("ramps", 1.0)], gravity=-60.0, noun="ramps",
              blurb="zigzag ramps with a band of conveyor belts in the middle", gate=True, weight=0.05),
    composed("seesaw", [("rockers", 1.2), ("pegs", 1.0), ("funnel", 1.0)], gravity=-30.0, noun="planks",
              blurb="rocking planks, then pegs, then a funnel", weight=0.05),
    composed("rapids", [("ramps", 0.9), ("chutes", 1.5), ("bumpers", 1.0)], gravity=-30.0, noun="chutes",
              blurb="ramps, split-and-rejoin chutes, then bumpers", weight=0.05),
    composed("carnival", [("pegs", 0.7), ("wheel", 1.4), ("spinners", 1.3), ("pegs", 0.7)], gravity=-30.0, noun="arms",
              blurb="pegs, a big wheel, a row of spinning bars, then pegs", gate=True, weight=0.05),
    composed("quarry", [("sieve", 1.4), ("funnel", 1.0), ("pegs", 1.0)], gravity=-30.0, noun="bars",
              blurb="a sieve, a funnel, then pegs", weight=0.05),
    composed("tumble", [("funnel", 1.0), ("drums", 1.4), ("pegs", 1.0)], gravity=-30.0, noun="drums",
              blurb="a funnel dropping the field onto spinning drums, then pegs", weight=0.05),
    composed("labyrinth", [("ramps", 1.0), ("sieve", 1.3), ("chutes", 1.5)], gravity=-30.0, noun="bars",
              blurb="ramps, a sieve, then split-and-rejoin chutes", weight=0.05),
    composed("orchard", [("pegs", 1.0), ("rockers", 1.3), ("pegs", 1.0)], gravity=-30.0, noun="planks",
              blurb="pegs, rocking planks, then more pegs", gate=True, weight=0.05),
    composed("pinball", [("bumpers", 1.1), ("rockers", 1.2), ("funnel", 0.9)], gravity=-30.0, noun="bumpers",
              blurb="bumpers, rocking planks, then a funnel", weight=0.05),
    composed("gallery", [("pegs", 1.0), ("sieve", 1.3), ("funnel", 1.0)], gravity=-44.0, noun="pegs",
              blurb="pegs, a sieve of tilted bars, then a funnel", weight=0.05),
    composed("spillway", [("chutes", 1.5), ("pegs", 1.0), ("funnel", 0.9)], gravity=-30.0, noun="chutes",
              blurb="split-and-rejoin chutes, pegs, then a funnel", weight=0.05),
    # The twin finish, on trial. Every other stage hands the race to whoever
    # leads the queue at the throat; this one forks the run-in, so the last
    # thing that happens before the line is a bounce picking a side. The stack
    # under it is chosen to deliver a bouncing field rather than a sorted one:
    # chutes swap sides, bumpers scatter, and the pegs above the fork mean no
    # marble arrives already committed to an exit.
    composed("delta", [("chutes", 1.3), ("bumpers", 1.0), ("pegs", 1.0)], gravity=-30.0, noun="chutes",
              blurb="chutes and bumpers into a finish that forks — the last bounce picks a side",
              gate=True, twin=True),
    # Trial: the first stage with a force in it rather than only shapes. Pegs
    # set the field spreading, magnets pull it off line, pegs again so the
    # deflection has something to argue with before the run-in.
    composed("lodestone", [("pegs", 1.0), ("magnets", 1.3), ("pegs", 1.0)], gravity=-30.0, noun="magnets",
              blurb="pegs, then magnets that pull the marbles off line, then more pegs", gate=True),
    # Trial: the stage the holding trap is for. Three things in the stack are
    # measured rather than chosen, all of them pace. The trap band has to be
    # the big one (1.6 against 0.8) because the pit is 148 px of fixed height
    # — the door's swing plus the bore's depth — and a band that cannot hold
    # it and some air above it builds no pit at all. Bumpers under the pit,
    # not pegs: the stack finishes about 9 s at gravity -30 either way, and
    # bumpers is what carries the retried attempt to 12.3-12.8 s against the
    # 11.5 s floor, where pegs left it on 11.4. And the throat, because the
    # trap spreads the field by design and the throat is the one thing in the
    # kit that gathers it: with it, a runner-up crosses on 56-75% of seeds.
    composed("trapdoor", [("pegs", 0.8), ("trap", 1.6), ("bumpers", 0.8)], gravity=-30.0, noun="the trapdoor",
              blurb="pegs, a trapdoor pit that holds a marble and lets it go, then bumpers",
              gate=True),
<<<<<<< HEAD
    # World 3, polarity swap (docs/10, physics/worlds/polarity.py; the
    # measurements are in docs/06, "World 3"). Trial: each races when a level
    # names it. Two stacks were changed by what QA found. honeypot opens with
    # a funnel, not pegs: behind pegs the field arrived over eight seconds
    # and the grip had the whole field on 2 races in 24; the funnel's throat
    # drops everyone into it (44 in 48), and it runs at -36 because the hold
    # adds a second or so. maelstrom puts the arm last and pegs first: with
    # the band's magnets at the top, the flip at halfway kicked the stragglers
    # still sitting there into the ceiling (15 of 90 parked; now 7 of 103).
    composed("crossfire", [("pegs", 1.0), ("tug", 1.3), ("pegs", 1.0)], gravity=-30.0, noun="magnets",
              blurb="pegs, a magnet on each wall pulling against the other, then pegs", gate=True),
    composed("sidewinder", [("pegs", 0.7), ("side-magnets", 2.0), ("pegs", 0.7)], gravity=-30.0, noun="magnets",
              blurb="pegs, magnets down one side of the frame, then pegs", gate=True),
    composed("detour", [("pegs", 0.4), ("detour", 2.8), ("pegs", 0.5)], gravity=-30.0, noun="lanes",
              blurb="pegs, a split into a long shielded lane and a short magnet lane, then pegs", gate=True),
    composed("carousel", [("pegs", 0.6), ("arm", 2.4), ("pegs", 0.6)], gravity=-30.0, noun="the magnet arm",
              blurb="pegs, a rotating arm with a magnet on each tip, then pegs", gate=True),
    composed("honeypot", [("funnel", 0.9), ("clump", 1.8), ("pegs", 0.8)], gravity=-36.0, noun="the big magnet",
              blurb="a funnel dropping the field onto one big magnet, then pegs", gate=True),
    composed("maelstrom", [("pegs", 0.5), ("magnets", 1.1), ("arm", 2.0)], gravity=-30.0, noun="magnets",
              blurb="pegs, a band of magnets, then a rotating magnet arm", gate=True),
=======
    # World 6, the dice track (trial; docs/06 "World 6" has their QA). The dice
    # sections are geometry; the dice themselves are the levels' mechanics.
    composed("dicetrack", [("dicegate", 2.2), ("pegs", 1.0)], gravity=-34.0, noun="dice gate",
             blurb="a dice gate that opens one of three lanes, then pegs"),
    composed("dicegrid", [("runway", 0.8), ("pegs", 1.0), ("sieve", 1.3), ("funnel", 1.0)], gravity=-40.0,
             noun="start grid", blurb="a start grid that drops at once, then pegs, a sieve and a funnel"),
    composed("diceblock", [("diceblock", 1.8), ("funnel", 0.8)], gravity=-40.0, noun="blockers",
             blurb="six blockers a die can remove, then a funnel"),
    Stage("dicetriple", stagekit.compose([("dicetriple", 1.0)], top_frac=0.93, bottom_frac=0.15), -150.0,
          "dice gates", "three dice gates, one under the other",
          # One section holding three gates (a band each would lose two margins
          # apiece, and three gates only just fit the frame without them).
          lambda style, segments: "a stage of " + ", then ".join(["a dice gate"] * 3),
          parts=(("dicetriple", 1.0),)),
    composed("dicesurface", [("surfaceramps", 1.0), ("surfaceramps", 1.0), ("surfaceramps", 1.0)], gravity=-60.0,
             noun="ramps", blurb="three bands of zigzag ramps, each with a surface a die rolls"),
    composed("dicefinal", [("runway", 0.8), ("dicegate", 2.0), ("pegs", 0.6)], gravity=-60.0, noun="dice gate",
             blurb="a start ramp behind a gate, a dice gate into three lanes, then pegs"),
>>>>>>> wp7-w6
    # COMPOSED-STAGES-END
]

STAGE_BY_ID: dict[str, Stage] = {st.id: st for st in STAGE_SPECS}
_LIVE_TOTAL = sum(st.weight for st in STAGE_SPECS if st.live)
# Derived names, kept because web, tasks and the tests read them.
STAGES = {st.id: (st.weight / _LIVE_TOTAL if st.live else 0.0) for st in STAGE_SPECS}
LIVE_STAGES = [st.id for st in STAGE_SPECS if st.live]
STAGE_GRAVITY = {st.id: st.gravity for st in STAGE_SPECS}
STAGE_NOUN = {st.id: st.noun for st in STAGE_SPECS}
STAGE_BLURB = {st.id: st.blurb for st in STAGE_SPECS}
SPINNER_STAGES = {st.id: st.spinners for st in STAGE_SPECS if st.spinners}
SPINNER_ROWS = {st.id: st.spinner_rows for st in STAGE_SPECS if st.spinners}
WHEEL_STAGES = {st.id: st.wheel for st in STAGE_SPECS if st.wheel}
GATE_STAGES = tuple(st.id for st in STAGE_SPECS if st.gate)
TWIN_STAGES = tuple(st.id for st in STAGE_SPECS if st.twin)
BUILDERS = {st.id: st.build for st in STAGE_SPECS}


@dataclass(frozen=True)
class Mechanic:
    """A level's `section`: something done to a built stage once its marbles
    are placed, through the round's rig (generators/mechanics.py).

    apply   apply(rig, space, style, balls, w, h): registers clocks, zones,
            doors, forces, effects on `rig`; `rig.rng` for any random choice.
    stage   the stage a level gets when it names this section and no stage.
    blurb   one line for people; the render's words come from the stage.

    A mechanic that needs geometry of its own belongs in a stagekit section
    and a composed stage (weight 0 until `factory stage-qa` passes it); this
    is for what changes an existing stage. See docs/10-mechanics.md.
    """

    id: str
    apply: Any
    stage: str | None = None
    blurb: str = ""


# One line per mechanic, as STAGE_SPECS has one per stage. Empty until a
# world's WP7 lands one.
MECHANIC_SPECS: list[Mechanic] = [
    # MECHANICS-BEGIN
<<<<<<< HEAD
    # World 3, polarity swap.
    Mechanic("magnet-flip", polarity.magnet_flip, stage="lodestone", blurb="the magnets pull, then push from halfway"),
    Mechanic("reverse-finish-magnet", polarity.reverse_finish, stage="lodestone",
             blurb="a magnet under the finish line pushes back"),
    Mechanic("rotating-magnet-arm", polarity.rotating_arm, stage="carousel", blurb="the arm's tip magnets pull hard"),
    Mechanic("shielded-lane", polarity.shielded_lane, stage="detour",
             blurb="the magnet lane's magnets pull hard enough to cost the short cut"),
    Mechanic("magnet-clump", polarity.magnet_clump, stage="honeypot",
             blurb="the big magnet grips the whole field, then lets go"),
    Mechanic("all-magnets", polarity.all_magnets, stage="maelstrom",
             blurb="band magnets flip, the arm pulls, the finish pushes back"),
=======
    # World 6, the dice track (physics/worlds/dice.py).
    Mechanic("dice-gate-paths", dice.dice_gate_paths, stage="dicetrack", blurb="a die picks one of three lanes"),
    Mechanic("dice-start-grid", dice.dice_start_grid, stage="dicegrid", blurb="every marble rolls; high roll starts in front"),
    Mechanic("dice-remove-obstacle", dice.dice_remove_obstacle, stage="diceblock", blurb="a die removes one of six blockers"),
    Mechanic("dice-gates-duel", dice.dice_gates_duel, stage="dicetriple", blurb="three dice gates, each picks a lane"),
    Mechanic("dice-round-count", dice.dice_round_count, stage="dicegrid", blurb="a die sets how many rounds, one to three"),
    Mechanic("loaded-dice", dice.loaded_dice, stage="dicetrack", blurb="every die lands on the hardest lane"),
    Mechanic("dice-surface", dice.dice_surface, stage="dicesurface", blurb="a die rolls each band's surface: ice, sand or plain"),
    Mechanic("handicap-start", dice.handicap_start, stage="plinko", blurb="a die picks one marble to start early"),
    Mechanic("handicap-back-start", dice.handicap_back_start, stage="dicegrid",
             blurb="a rolled grid; the level's back marker starts last with no die"),
    Mechanic("dice-final", dice.dice_final, stage="dicefinal", blurb="rolled grid, rounds, path and surface"),
>>>>>>> wp7-w6
    # MECHANICS-END
]
MECHANICS: dict[str, Mechanic] = {m.id: m for m in MECHANIC_SPECS}
