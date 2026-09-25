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
| `rig.door(..., lights=[ids] \| clock, look="pass" \| "block", lamps=[(x, y)])` | a colour gate (World 9): the lamps show `lights` instead of who passes; `look="pass"` draws the shut bar in the lamps' colours on a pale rim (those may pass), `"block"` draws it pale with the lamps crossed out (those may not); `lamps` puts them where the queue cannot hide them. Without a look a door is drawn as before, and its recording has no new keys |
| `rig.pair_force(strength, reach=4.0, soft=1.0, trait="charge", when=clock)` | every pair pushes apart (> 0) or pulls together (< 0), `strength` x gravity at contact, zero at `reach` x the pair's radii (the magnet's softened law), per substep. Each marble's share is its cast trait (`charge`, default 1); `when` scales it; `force_immune` marbles skip it |
| `rig.pair_force(strength, reach=4.0, soft=1.0, trait="charge", when=clock, skip_immune=True, newton=False)` | every pair pushes apart (> 0) or pulls together (< 0), `strength` x gravity at contact, zero at `reach` x the pair's radii (the magnet's softened law), per substep. Each marble's share is its cast trait (`charge`, default 1); `when` scales it; `force_immune` marbles skip it unless `skip_immune=False`; `newton=True` makes the pair's forces equal and opposite, so the heavier marble of a pair moves less (two equal marbles move as without it). World 8 uses both |
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
| `rig.effect("prop", clock=…, track=True, look="pumpkin", radius=r, color=…)` | a prop drawn where its clock says: the clock's value is `[x, y]`, or None to hide it. How a world draws a body of its own that moves and is not a marble (World 4's pumpkins record their body's position this way); `look` picks a drawing, today only `pumpkin` |
| `rig.effect("field", clock=…, reach=k, sign=1 \| -1)` | while the clock is truthy (always, with none), every pair of visible marbles closer than `k` x their summed radii is drawn with the pair force between them: facing arcs that brighten as they close (a push), a dotted tether (a pull). Drawn from the trace's positions, under the marbles — World 8's repulsion |

Gate lights, surface textures and outward magnet chevrons need no effect
call: they come with the door, the zone, the polarity clock.

The presentation (`[presentation]`, physics `present.py`) sits over all of
this and reads the same recording: no fire and no chip for a marble that is
`hidden` (eliminated, or in a blackout), the eliminated at the foot of the
leaderboard, dimmed, and no progress bar on a race with `no_finish_line`.
A section needs to do nothing for it.

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

## What World 2 built (L11–L20)

The worked example above is the shape; `factory/generators/physics/worlds/trapdoor.py`
is the real thing, and it went a different way in one respect worth copying:
the stage kit's holding `trap` stays as it was (the pinned `trapdoor-cast`
trace depends on it), and World 2 brought its own **panel** — a lid (a
`rig.door`) over a pit (two `rig.out_zone`s) — built by sections `trap1` (and `trap1wide`),
`trap2`, `trap3` (one, two, three panels at the foot of a band), `bowl` and
`relaystation`, registered into `stagekit.SECTIONS` from the world module.
Nine trial stages use them (`trapfall`, `trapstairs`, `trapline`, `decoys`,
`tripwire`, `sinkhole`, `relay`, `trapwalk`, `pitfall`; docs/06 "World 2"),
and each level's mechanic only sets the panels' `opener(frame)`. Three things
a world with doors that open under marbles should know:

- **A door must not close through a marble.** At the kit's gravity a marble
  needs over a second to fall below a lid, and a door that closes on it is
  resolved by the solver shoving it back up. World 2's lids stay open while a
  marble is falling through (`_is_open`); another world's doors will want the
  same.
- **Events**: `trap_catch` (with `eliminated`, by `trapdoor`) when a pit
  takes a marble; `trap_opened` the first time each panel opens;
  `sensor_tripped` (L15); `handed_off` and `relay_dropped` (L17: a relay's
  first leg leaving the race at the gate, and a second leg that never gets
  to run). A handover is recorded as an elimination (`by: handoff`), so a
  relay's `eliminations` count includes them; its story asks for a catch.
- **A held marble is not parked.** Stage QA counts a marble resting on a
  shut, level door as held (`stage_qa._on_shut_floor`), as it does one in a
  trap's pit: a relay pen, a drain between openings.

## What World 9 built (L81–L90)

`factory/generators/physics/worlds/colour_gates.py`: a colour gate is a funnel
down to a wide level bar (`rig.door` with `look`), built by the sections
`colourgate`, `icegate` (arms of World 5's ice) and `boxgate` (room under the
bar for L88's penalty box). A level's mechanic sets each gate's rule — lit for
seeded colours, locked for the leader's colour, cycling every colour a second —
and L86/L90 re-clock World 2's trapdoor lid into a colour gate. Two things a
world with selective doors should know:

- **A door that lets some marbles through must not shut on one that is
  going through.** A marble the rule lets pass, touching the bar, stays in the
  pass list until clear (`Gate.crossing`), whatever the rule says next.
- **Every selective door needs an end.** A lit gate opens for everyone after
  its wait, a reverse gate after its lock, a cycling gate lights everyone in
  turn, and any gate opens for good once a marble has sat on it `GIVE_UP_S`
  (15 s). Stage QA ran each level 30 s past the winner to check it
  (docs/06, "World 9"). Marbles waiting on a shut bar are a `rig.hold`.

Events: `gate_lit` (colours on screen), `gate_locked`, `gate_opened`,
`gate_broken` (L88), plus World 2's `trap_opened` and `trap_catch`. None
reveals a result.
## What World 4 built (L31–L38)

`factory/generators/physics/worlds/haunted.py`: a `maze` section (rows of
forks; each corridor ends at a gap in its floor with a roofed dead end past
it, an always-armed `rig.out_zone`, event `dead_end`) and a `coffin` section
(World 2's `panel` under a funnel's throat, its lid drawn in wood), on four
trial stages (`haunted`, `pumpkinpatch`, `coffin`, `hauntedfinal`; docs/06
"World 4"). Three things other worlds can reuse:

- **A body that is not a marble.** A pumpkin is a kinematic pymunk body (a
  bumper) that the world's `on_frame` hook turns dynamic the frame a marble
  touches it. Its position is a clock, drawn by a *tracked* prop (above), so
  a redraw needs no pymunk. It is in the space but never in `balls`: no
  sound, no stall check, no outcome. It leaves the course the way a marble
  would (below the line, or into an always-armed out zone).
- **A web that tears.** `rig.zone(first_only=True, when=clock, appear=True)`
  with a clock that goes false a fixed time after `zone.victim` is set: the
  first marble in is held, and the web is drawn only while it holds.
- **A blackout that ends.** A clock that turns on at a race fraction and off
  at another, clamped to a minimum and a maximum number of seconds, so the
  dark is always about the same length however fast the leader goes.

`dead_end` is hidden from the copy brain with `trap_catch`
(`Outcome.without_winner`): it says a marble went out and when.
## What World 8 built (L71–L80)

`factory/generators/physics/worlds/repel.py`: one pair force (`repel`) and
the field drawn with it, on every level. The core gained two options on
`pair_force` (`newton`, `skip_immune`, both off by default, so nothing built
before moves) and the `field` effect (both renderers, through
`render_mech.pil_field` / `pg_field`, called once a frame after the
structure). Ember is immune to magnets and wind, not to the other marbles:
World 8 passes `skip_immune=False`, and its `charge` (cast.toml) makes its
pairs push hardest while its mass makes it give way least.

Geometry a mechanic has to size from the marbles — a corridor one marble wide,
a merge gap — is built by its section (`corridor`, `merge`) as always-shut
doors for the kit's biggest marble, so the stage races without the mechanic,
and built again by the mechanic for the marbles racing: only after they are
placed are their radii known, and a door is the one wall that can be taken
out and added then. The sections that are plain geometry (`twinlanes`,
`edgepits`, `ramp`, `lane`) register with the kit on import, as World 2's do.
Five trial stages (`singlefile`, `blockade`, `mergelane`, `pitfunnels`,
`threeramps`); docs/06 "World 8" has their numbers, and one lesson for any
world with a push: a marble in a throat holds the next one above it, so a
push that reaches past a throat parks the queue behind it.

