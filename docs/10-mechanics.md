# Mechanics: how a world adds what a shape cannot do

Season 0's worlds 2–10 need things the stage kit's sections (docs/04) cannot
say by being in the way: a pit that takes a marble out, a magnet that flips
at halfway, ice, a gate one colour may pass, marbles that push each other
apart, a blackout. WP7-core put the hooks for all of them in one place,
`factory/generators/mechanics.py`, so a world agent adds a world as **sections
and a registry line**, and never edits the simulation, the renderers, the
trace or the outcome.

Read docs/08 (the series contracts) first. This page is how to build on them.

## The rules the hooks keep

1. **Opt-in.** Every race gets a `Rig`. One nobody registers anything on is
   not `live`, and the simulation then runs exactly the code it ran before
   WP7. `tests/test_mechanics.py` pins the traces of existing races to the
   hashes they had on main before this landed; frames, audio and facts of
   twelve races (both renderers) were compared byte for byte too.
2. **Deterministic from the seed.** A mechanism's random choice comes from
   `rig.rng` — a stream derived from the round's seed and nothing else — so
   adding a mechanic never moves a draw the build made, and the same seed is
   the same race. No wall clock, no `random` module state.
3. **Recorded, not re-simulated.** Anything that changes over time is a
   *clock*: evaluated once a frame, recorded as change points in
   `style.mech`, and read by both renderers. A redraw from `trace.json` needs
   no pymunk and draws the shipped frame (tested for both engines).
4. **Never steered** (docs/08 rule 2.4). A clock may react to the race — how
   far it has come, who leads — because that is a mechanism a viewer can
   see. It may not take an entrant's *identity* as a reason, and a seed is
   never searched for who falls: `story.must` may ask for `eliminations:
   ">=2"`, never for `eliminated_includes: blaze` (that stays identity-gated).

## Two places a world's code goes

| you need | write | register |
|---|---|---|
| new geometry in a band (a maze band, a sand pit, an arena floor) | a **stagekit section** `section(space, w, top, bottom, rng, style)` in `factory/generators/stagekit.py`, calling `rig_of(style)` for hooks | `SECTIONS` + `SECTION_WORDS` in stagekit, then a `composed(...)` stage in `physics/registry.py` **with weight 0** |
| something done to a built stage (flip its magnets, spring its trap, a blackout) | a **mechanic** `apply(rig, space, style, balls, w, h)` | a `Mechanic(id, apply, stage=...)` line in `MECHANIC_SPECS` (physics/registry.py) |

A level names a stage with `params.stage` and a mechanic with
`params.section`. A mechanic with `stage=` supplies the stage for a level
that names none. A `section` that is not registered is ignored with a
warning, as it always was — so a typo renders a plain race; stage QA
(below) is what catches it.

Sections register while the stage is built; the mechanic runs after the
marbles are placed (so it can read `balls` and `style`); then the round's
`mirror` and `friction` transforms apply; then filters are bound.

## The hooks

All coordinates are pymunk's (y up, the finish line at y = 110). Times are
seconds from the start of the simulation, before the opening skip; the
recording shifts them to the clip's clock.

### Reading

| | |
|---|---|
| `rig_of(style) -> Rig` | the round's rig, from inside a stagekit section |
| `rig.rng` | the mechanics' own seeded `random.Random` |
| `rig.knob(name, default)` | a level's setting: `params.mechanics.<name>` (e.g. `flip_at`) |
| `rig.round`, `rig.params` | which round (0-2) and its params (after `round_params`) |

### Clocks — `fn(frame) -> JSON value`, once a frame, recorded

| | |
|---|---|
| `rig.clock(name, fn)` | any value; `fn` gets a `Frame`: `frame, t, progress, names, positions, alive, finished, leader, values` |
| `rig.at(name, t=… \| progress=…, before, after)` | switch once at a time or a race fraction |
| `rig.cycle(name, period, on=0.5, phase=0, values=(True, False))` | a gate that cycles |
| `rig.window(name, t0=, t1=)` / `(p0=, p1=)` | true inside a window |
| `rig.countdown(name, t)` | whole seconds left, then `None` (what a timer shows) |
| `rig.on_frame(fn)` | a per-frame hook (move a kinematic body, `rig.emit(...)`) |
| `rig.emit(kind, index, **data)` | an Event now |
| `rig.hold(clock)` | the field is held on purpose while the clock is truthy (a start gate, a die still rolling): the stall check does not count those frames |
| `rig.clip_rounds = n` | set in the heat, the clip runs `n` rounds, never more than `params.rounds` (World 6's round die) |

`progress` is how far the leader has come from the start row to the line,
0..1, and never goes back: "halfway" is `progress=0.5`.

### Elimination

| | |
|---|---|
| `rig.out_zone(rect=(x0, y0, x1, y1) \| poly=[…], when=clock, event=kind, label=…, show=True)` | a marble whose centre is inside while `when` is truthy (always, if None) is **eliminated**: removed from the simulation that frame, `eliminated` Event (data `by`: the label), plus `event` if given |
| `rig.eliminate(index, by=…, event=…)` | the same from a hook |
| `rig.no_finish_line()` | an arena: nothing crosses, the result is who is left |

An eliminated marble keeps its last position in the trace (the arrays are
one shape) and is not drawn from its frame on; the pygame renderer bursts
sparks in its colour where it went.

### Surfaces

| | |
|---|---|
| `rig.surface(space, a, b, kind="ice", thickness=6, friction=None)` | a static segment with the surface's friction and bounce, drawn with its colour |
| `rig.zone(rect \| poly, kind="sand", damping=None, friction=None, first_only=False, when=None, event=None, appear=False)` | a region that drags: `damping` 1/s on velocity every substep (default the kind's), a marble's own friction set to `friction` while inside; `first_only` (a cobweb) affects only the first marble in, with `event` when it is caught; `appear`: drawn only while `when` is truthy (a surface rolled mid-race is not on screen before the roll) |
| `rig.breakable(space, a, b, kind="thin_ice", hold=(0.8, 2.0), thickness=5)` | breaks after a **seeded** amount of load (contact-seconds x mass, from `hold`); cracks drawn at half; `broke` Event |

Kinds (`mechanics.SURFACES`): `ice` (friction 0.02), `sand` (0.95, damping
1.4), `mud`, `cobweb` (damping 3, no friction change), `thin_ice`, `slush`
(0.35, damping 0.25: ice going soft, World 5's melt). Zones are drawn with a
texture: an ice sheen, a sand (or slush) grain, cobweb threads; a slanted
`poly` zone keeps only the marks inside it.

### Per-entrant filters and forces

| | |
|---|---|
| `rig.door(space, a, b, closed=clock, passes=[ids] \| clock, color=rgb)` | solid while `closed` is truthy (always, if None) for everyone except `passes` — a list of entrant ids or a clock whose value is one. Drawn in `color` with a light per passing entrant's colour; faint while open |
| `rig.pair_force(strength, reach=4.0, soft=1.0, trait="charge", when=clock)` | every pair pushes apart (> 0) or pulls together (< 0), `strength` x gravity at contact, zero at `reach` x the pair's radii (the magnet's softened law), per substep. Each marble's share is its cast trait (`charge`, default 1); `when` scales it; `force_immune` marbles skip it |
| `rig.magnet_polarity(clock)` | every magnet's pull times the clock's value: 1 pulls, -1 pushes (chevrons drawn outward), 0 off. `force_immune` still skips. The value may be a list, one number per magnet in `style.magnets` order (World 3: the band flips while the arm pulls and the finish pushes) |
| `rig.magnet_track(clock)` | magnets that move: the clock's value is a list, one `[x, y]` (or null: where it was built) per magnet. The field, both renderers and `launched` use it; carrying the core is the section's (a kinematic body). World 3's `arm` section |
| `rig.moving_wall(space, a, b, offset=clock)` | a kinematic wall offset by the clock's `[dx, dy]`: closing walls, a pusher |

A door gives each marble a collision bit, so a race holds at most 12
(`mechanics.MAX_ENTRANTS`).

### Render effects

| | |
|---|---|
| `rig.effect("blackout", clock=…)` | marbles and trails hidden and a dark veil while the clock is truthy; sound carries on |
| `rig.effect("countdown", clock=…, at=(x, y))` | the clock's value drawn as a number |
| `rig.effect("die", clock=… \| value=k, at=(x, y), size=px, layer="top" \| "under", tints={"1": rgb})` | a die face with pips; the clock's value is None (not drawn), a face, or `{"f": face, "s": "roll" \| "set" \| "lit" \| "dim"}` — tumbling while it rolls, ringed when lit, faded when dim. `worlds/dice.roll` registers one with its clocks |
| `rig.effect("prop", clock=…, at=(x, y), radius=r, color=[r, g, b])` | a marble drawn there while the clock is truthy (always, with no clock): a picture with no body, never an entrant, never in the outcome — L50's purple watcher |

Gate lights, surface textures and outward magnet chevrons need no effect
call: they come with the door, the zone, the polarity clock.

## Level params

| param | what it does |
|---|---|
| `section` | the mechanic to apply (registry `MECHANICS`) |
| `format` | `race` (default), `elimination`, `last_standing` — the Outcome's format |
| `win` | elimination only: `first_across` (default: the first across wins; one left before that also wins) or `last_standing` (decided when one marble is left racing; crossing the line counts as surviving, above everyone out). `format: last_standing` defaults to it |
| `teams` | `{blaze: 2, tide: 2}`: marbles per persona; ids `blaze.1`, `blaze.2` (every persona suffixed), colours shaded, `team` on each; `outcome.facts.teams` maps id → persona |
| `mechanics` | a section's knobs, read with `rig.knob` |
| `rounds` | 1, 2 or 3 |
| `round_params` | a list, one dict per round, laid over the round's params: `stage` (`"same"`: the heat's), `layout: k` (build round k's layout again, fresh marbles), `mirror: true` (the stage reflected left to right; a trapdoor refuses), `friction: x` (every static surface times x), or any knob |

All of them travel from a season level to the make-clip task
(`planning.PARAM_KEYS`, `tasks.KINDS`) and are allowed in a batch row.

Up to 12 marbles race on any stage with room: when the start row cannot
hold the field, it starts from a grid of rows staggered by half a lane; a
grid that would reach the stage's structure is refused with the reason.

## Outcome and event kinds

Placements rank finishers by crossing, then marbles still in the race by
how far they got, then the eliminated, **the last one out first**. The
survivor that decided a `last_standing` race ranks first. Statuses:
`finished`, `running`, `stopped`, `eliminated`. Facts gain `eliminations`,
`teams` and `win` (`finish` | `survival`) only when there are any, so a
plain race's outcome is what it was.

Event kinds the core emits: `eliminated` (data `by`), `broke`, plus the
existing `round_start`, `lead_change`, `finish`, `trap_catch`, `launched`.
A world names its own for what its mechanism does:

- snake_case, past tense, about the **mechanism**: `flipped`, `gate_opened`,
  `webbed`, `pushed`. Never an entrant or a result (`blaze_out` is two wrongs).
- reuse an existing kind when it means the same thing: a timer trap that
  eliminates passes `event="trap_catch"` so L11's `any_event: trap_catch`
  holds.
- a kind that reveals who won or fell must be added to `hidden` in
  `Outcome.without_winner` (factory/series/outcome.py), or the copy brain
  sees the result.

Story predicates: add `eliminations: ">=2"` (a count, a mechanism) and
`any_event: <your kind>`. `eliminated_includes` stays identity-gated.

Standings (docs/08 "Standings"): elimination scores one point per entrant
outlasted, never counting a teammate; a team race scores the persona, the
sum of its marbles' points by default or the best with

```toml
[teams]
mode = "best"   # or "sum"
```

## Worked example: a timer trapdoor that eliminates (L11)

L11 is `stage: trapdoor, section: timer-trap, format: elimination`, teams.
The trapdoor stage already has a pit; the mechanic springs it for good at a
hidden, seeded moment, and whoever is in the pit then is out.

**1. The mechanic** — in a world module, e.g.
`factory/generators/physics/worlds/trapdoor.py`:

```python
def timer_trap(rig, space, style, balls, w, h):
    """The pit's floor springs once, at a hidden time; whoever is in it is out."""
    if not style.traps:
        raise ValueError("timer-trap needs a stage with a trapdoor")
    at = float(rig.knob("open_at") or rig.rng.uniform(5.0, 9.0))  # seeded, never steered
    rig.window("sprung", t0=at, t1=at + 1.0)
    for hx, hy, bore, depth, _period, _phase in style.traps:
        rig.out_zone((hx, hy, hx + bore, hy + depth), when="sprung",
                     event="trap_catch", label="trapdoor")
    if rig.knob("show_timer", False):          # L18: the countdown on screen
        rig.countdown("trap_in", at)
        rig.effect("countdown", clock="trap_in", at=(w / 2, h * 0.82))
```

**2. Register it** in `physics/registry.py`, between the markers:

```python
from .worlds.trapdoor import timer_trap
MECHANIC_SPECS: list[Mechanic] = [
    # MECHANICS-BEGIN
    Mechanic("timer-trap", timer_trap, stage="trapdoor", blurb="the pit springs once, at a hidden time"),
    # MECHANICS-END
]
```

A mechanic that needs a new *stage* (geometry of its own) adds it with
`composed("trapdoor-gauntlet", [...], ...)` and **weight 0**: a trial stage
races whenever a level names it and is never picked at random, so nothing
reaches the random pool before it has passed QA.

**3. Stage QA it** (docs/06): the plain gates, then the elimination ones.

```
factory stage-qa --stage trapdoor --section timer-trap --seeds 48
factory stage-qa --stage trapdoor --section timer-trap --format elimination --seeds 48
factory stage-qa --stage trapdoor --section timer-trap --format elimination \
    --cast main --teams blaze=2,tide=2 --seeds 48
```

For an elimination race QA measures, per stage: **finishers a race**,
**eliminations a race**, **eliminating** (share of races where the mechanism
took anyone out), **decided** (a result: someone crossed or someone was
left), and the **last-two gap** (the runner-up's margin when two cross,
otherwise from the second-last exit to the decision). The gates are
`stage_qa.ELIMINATION_GATES`: eliminating 60%+, at least one elimination a
race, 95% decided, and the last two within 4.0 s at the median. They were
set before any world was measured; change them with the numbers that say
so, as docs/06 records every gate. A new stage also passes the ordinary
gates before it gets a weight.

**4. Unblock the levels** in `channels/main/season/s0.yaml`: for each level
the mechanic serves, set `status: ready`, `blocked_on: null`, check
`params` (`section`, `stage`, `teams`, `mechanics` knobs) and — when the
build is not what the plan described — a `note:` saying so (docs/08 rule
2.6). Then `factory season check` (0 errors) and
`factory season plan --levels L11..L11`. A world's WP7 must pass stage QA
three days before its first level (docs/08, "Calendar").

**5. Test it** beside `tests/test_mechanics.py`: the mechanic eliminates on
some seed of a few, the same seed gives the same `style.mech`, and a redraw
of one clip equals its shipped frames in both engines. Leave the pinned
traces alone: if they move, something that was not opt-in changed.
