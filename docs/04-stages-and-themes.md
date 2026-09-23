# Stages and themes

## Stages

A race needs a descent, and each shape of descent is a different picture to
the similarity gate and a different question to the viewer. There are two
kinds: eleven stages built by hand, one function each, and eleven **stacked
from sections** (below). Every stage is one entry in `STAGE_SPECS` in
`factory/generators/physics.py` — gravity, noun, blurb, weight, spinners,
throat — and nothing else in the code keeps its own list. The live numbers
for all of them are on the **Stage QA** page (docs/06).

### Built by hand

| stage | what the viewer sees | measured (24 seeds, through the retry loop) |
|---|---|---|
| **zigzag** | six to nine full-width ramps, alternating sides — fast, the classic | 24 finish, median 13.7 s |
| **pegboard** | a Galton board: rows of small pegs, nothing to rest on | 24, median 14.2 s |
| **bumpers** | pinball: a lattice of large elastic bumpers, 3–4 spinning bars | 24, median 13.2 s |
| **funnels** | three or four funnels in series, throats offset — every throat a bottleneck | 24, median 13.6 s |
| **gauntlet** | a narrowed lane of 5–6 lane-wide spinning bars: gates, not obstacles | 23, median 14.4 s |
| **cascade** | chutes that split at a tilted peak and rejoin at a V, five or six rows | 24, median 13.1 s |
| **pinwheel** | one big four-armed wheel mid-frame, pegs above and below | 24, median 14.1 s |
| **sieve** | three or four rows of short tilted bars, gaps sized to a marble | 24, median 12.4 s |
| **pachinko** | pegs on arcs around a central bumper | 24, median 11.5 s |
| **rockers** | planks that rock on a pivot, tipping a marble off the low end | 23, median 16.3 s |
| **drums** | big spinning drums that carry a marble sideways, every gap sized to clear one | 24, median 11.6 s |

Pace is set with gravity per stage, not geometry — the geometry is what keeps
the solver honest (slopes near 0.4, throats measured in radii), and gravity is
a dial that cannot jam. A seed picks a stage by weight unless a task names
one (`make-clip` has a `stage` parameter; `course` is the old name and still
accepted). When an attempt stalls or finishes under the QC floor, the retry
leans gravity the way the failure points (quicker after a stall, slower after
a too-fast finish) on a seed derived from the original, up to five attempts.

Three things were measured and cut while building these: a flat cap on the
cascade's peak (a ledge marbles rest on), a point apex (marbles balance on
it), and a gauntlet of short bars (every seed fell straight past them under
the floor, whatever the gravity; the bars now span the lane so a marble must
wait for a gap to turn round). An earlier wedges stage — chevrons staggered
like pegs — had three traps and seven finishes in 24, and is not offered.

### Stacked from sections

A section fills one horizontal band of the frame with one kind of obstacle;
a stage is a list of sections, top to bottom, each with a share of the
height. The kit is `factory/generators/stagekit.py`:

| section | what it puts in its band |
|---|---|
| `pegs` | offset rows of small pegs, a marble's width apart, rows 66 px or more apart |
| `bumpers` | a lattice of big elastic bumpers |
| `funnel` | two ramps from the walls to one throat, 4.2–4.8 marble radii wide |
| `ramps` | zigzag ramps at slope 0.37–0.44 |
| `sieve` | rows of short tilted bars, tips a marble apart |
| `drums` | rows of spinning drums, every drum sized from the gaps around it |
| `rockers` | planks rocking about a tilt, tips clear of the walls, deflectors below |
| `spinners` | pairs of bars turning opposite ways, sweeps a marble apart |
| `wheel` | one four-armed wheel |
| `chutes` | a V then a split peak, with a marble's room under every throat |
| `belts` | conveyor belts from alternate walls, each at its own speed |
| `trap` | **new**: a pit with a hinged floor that swings away on a clock — it catches a marble, holds it for a beat and lets it go |

The rule that makes stacking safe: **nothing solid within a margin of a
band's edge** (0.06 of the width), so two neighbouring sections are further
apart than the biggest marble and cannot make a pocket between them. Every
clearance inside a section is sized from the marble too — the lessons the
hand-built stages taught one stuck marble at a time, written once.

| stage | stacked | gravity |
|---|---|---|
| **plinko** | pegs → wheel → pegs, throat | −31 |
| **switchback** | ramps → belts → ramps, throat | −60 |
| **seesaw** | rockers → pegs → funnel | −30 |
| **rapids** | ramps → chutes → bumpers | −30 |
| **carnival** | pegs → wheel → spinners → pegs, throat | −30 |
| **quarry** | sieve → funnel → pegs | −30 |
| **tumble** | funnel → drums → pegs | −30 |
| **labyrinth** | ramps → sieve → chutes | −30 |
| **orchard** | pegs → rockers → pegs, throat | −30 |
| **pinball** | bumpers → rockers → funnel | −30 |
| **gallery** | pegs → sieve → funnel | −44 |
| **spillway** | chutes → pegs → funnel | −30 |
| arcade *(trial)* | bumpers → spinners → pegs, throat | −30 |
| delta *(trial)* | chutes → bumpers → pegs, **twin finish** | −30 |
| trapdoor *(trial)* | pegs → trap → pegs | −30 |

Twelve are live and together take 37% of the random picks (0.05 each
against the hand-built stages' weights). arcade is in trial: it passes
everything but drama — the lead changed 1.1 times a race against a gate of
1.5 — so it races when a task names it and is never picked at random.
trapdoor is in trial as the first stage with a `trap` in it: it passes every
gate on 24 seeds (24 finish, 19 first try, runner-up 42%, 7 of 60 unfinished
marbles parked, none out of frame, median 13.2 s, lead 1.7) and on 48 fresh
seeds, and the pit held 55 marbles over those 24 seeds for a median of 1.8 s,
3.9 s at the ninetieth and 5.9 s at the worst. A new one is three steps: add a `_composed(...)`
line to the registry with weight 0 (trial — it races when a task names it,
never at random); run `factory stage-qa --stage <id> --calibrate --seeds 48`;
if every gate passes, give it a weight.

### Stage QA

`factory stage-qa` runs a stage over many seeds through the same retry loop a
render uses and measures what a viewer would notice: does it finish in the
window, first try; does a runner-up cross before the cut; how many unfinished
marbles are parked (under 20 px in the last two seconds) or out of the frame;
the median finish; how often the lead changes. `--calibrate` tunes gravity
toward a 14 s median but never below 30 — below that a race looks like the
moon, and a stage too quick at 30 needs more in its way, not less gravity.
`--report docs/06-stage-qa.md` writes the table. `stage_qa.contact_sheet`
draws each seed at four moments with the real renderer, for the half of QA
that numbers cannot do: it is how the three-peg cup and the crawling belt
below were found.

What QA caught while the eleven were built, and the fix now in the kit:

- **The three-peg cup.** Two peg rows 40 px apart: a marble falls between two
  pegs onto the offset peg below and sits in the triangle all race (36 of 64
  unfinished marbles on one stage). Rows are now 66 px apart or there is one.
- **The peg cradle and corner.** Pegs 49 px apart against a 57 px marble, and
  a peg 14 px from a wall. Pegs are now a marble apart, and a peg that would
  leave a wall gap smaller than a marble is left out.
- **No room under a throat.** A chute's V ended 45 px above the cap below.
- **The pivot trap.** A marble on a rocker's pivot is rolled one way, then
  back, forever; composed rockers rock about a tilt so the pivot drains.
- **The flat sieve.** Clamping edge-row bars to fit the band flattened them
  into ledges (8 of 15 parked marbles on one stage); rows are inset instead.
- **The crawling belt.** A belt drags only through friction — a marble gets a
  third of its speed — so at a tilt of 0.10 marbles crawled for seconds.
  Belts now tilt 0.17 and the speed decides who gains.
- **The moon.** Calibration first pushed three stages to gravity −13…−22.
- **Jiggled, not parked.** The agent's own QA rejected an orchard clip with a
  marble wedged between a rocking plank and the wall for half the race —
  moving all the time, so "moved under 20 px in two seconds" missed it.
  *Parked* now means no headway: less than 25 px further down the course in
  each of the last two 4-second windows. It also caught what follows.
- **Launched, not parked.** At gravity −30 a spinning bar with the
  hand-built bounce (0.72) sent marbles 375 px back up the frame. Composed
  stages' bars and wheels bounce 0.35 and turn 0.9–1.4 rad/s; their bumpers
  bounce 0.75, not 0.9, which had been juggling marbles in place.
- **The throat at low gravity.** The finish throat's arms slope 0.34, barely
  downhill at −30: marbles sat on them for the last eight seconds of a clip.
  On composed stages the throat is wider (0.21–0.24 w, no two-marble arch)
  and its arms slope about 0.5. The hand-built stages keep theirs.
- **The rocker at the wall.** A plank tip 61 px from the wall wedged a 57 px
  marble; tips now keep a marble's room and air, the outer planks rock about
  a strong tilt (0.24–0.32 rad) with the outer tip high so they drain
  inward, and the wall deflectors are gone — they only made a pocket under
  the tip.
- **Belts keep the order.** Stages built mostly of belts changed the lead
  about once a race; three were dropped, and belts appear once, mid-stage.
- **Held, not parked.** A marble sitting in the `trap` section's pit and a
  marble wedged behind a peg look identical in the last eight seconds: both
  still, both short of the line. The harness tells them apart by what the
  marble is sitting on rather than by how long it has been still, which is
  why the 25 px threshold did not move. A trap's door runs on a clock that
  does not care what is on it, so a marble in the pit is going to be let go
  and when is arithmetic — and a marble still in the pit after
  `stage_qa.TRAP_HOLD_CYCLES` periods has had the floor swing out from under
  it and stayed, so it is wedged and counts as parked again. On the trapdoor
  stage the exemption is what the verdict turns on: 12 parked in 117 with
  it, 16 in 117 without (48 seeds), against a gate of 12%.
- **A door that comes back fast throws marbles.** The trap's hinge makes a
  pinch impossible — the one corner where the door meets static structure is
  the pivot, and a gap that opens from zero cannot close on anything — but
  the closing sweep still bats whatever is left in the pit back up the feed
  ramp, and a marble that has to run the ramp again makes no headway. At a
  closing sweep of 0.22 of the cycle (tip 167-190 px/s) 21 of 119 unfinished
  marbles were parked above the pit; at 0.30 (122-139 px/s, inside the
  rocking planks' range) it is 12 of 117. Opening is free to be quick,
  because the door drops away from whatever is on it.

The same run measured the hand-built stages for the first time. Two pass
every gate (zigzag, funnels); the rest are on the QA page with the reason,
and they keep their weights until someone decides otherwise — the numbers
say bumpers parks more than half its unfinished marbles, so it is the first
candidate for a rebuild from sections.

## How hard the race is to call

A race that is decided in the first five seconds has nothing to say for the
next fifteen. Four things are measured over 20 seeds a stage, and they are
what "more twists" means here in numbers: how often the lead changes hands,
how often the marble leading at the half-way point goes on to win, how often
the finish is inside a second, and how often the winner had been last at
some point.

| stage | lead changes | half-way leader wins | finish inside 1 s | came from last |
|---|---|---|---|---|
| zigzag | 7.5 | 65% | 50% | 100% |
| pegboard | 4.0 | 80% | 50% | 45% |
| bumpers | 5.0 | 20% | 20% | 70% |
| funnels | 2.0 | 70% | 20% | 40% |
| gauntlet | 4.5 | 20% | 5% | 75% |
| cascade | 1.0 | 90% | 20% | 25% |
| pinwheel | 2.0 | 75% | 10% | 35% |
| sieve (throat) | 3.0 | 45% | 10% | 55% |
| pachinko | 4.0 | 60% | 50% | 40% |
| rockers | 6.0 | 53% | 5% | 63% |
| drums (throat) | 1.0 | 65% | 20% | 15% |

**What the first unattended renders taught.** Five clips came back and the
reviewing agent rejected two for marbles that never finished. The finish
measurement only asked whether *a* winner crossed, so a second number was
added — how many marbles end the clip motionless and short of the line —
and it was 47-69% on the pinwheel, the sieve and the drums. Each was a
pocket, found by drawing the last frame rather than reasoning about it: a
throat arm meeting the peg above it (pinwheel — the throat came off, and
its surprise went with it, 20% back to 75%; dead marbles cost more); a bar
tip 41px from a wall, and rows 82px apart, against a 60px marble (sieve);
drums 31px from a wall, drum rows 50px apart, and the lowest row sitting
in the throat's mouth (drums). Every gap on those stages is now sized from
what a marble needs, and the number is 1-5%.

Two things produced those numbers, and both replaced something that was
there for a reason that turned out not to be true.

**The run-in throat.** A narrow gap just above the line, on 72% of seeds, on
the bumpers and the gauntlet only. The field queues for it, jostles, and
comes out in a different order from the one it went in: on those two stages
the half-way leader stopped winning half the time and started winning a
fifth of the time, and the winner had been last at some point in 70-75% of
runs. A turning bar was tried in the same place first and made things worse
— a bar deflects whoever meets it at random, and deflection spreads a field
out rather than gathering it. The throat is off on the other four stages
because it measured worse on each: the zigzag already changes the lead five
to seven times on its own, the pegboard traded most of its close finishes
for a little surprise, and the funnels stage is already a row of throats.

**The twin finish.** The throat still settles the race several seconds early:
it gathers the field and then hands the win to whoever leads the queue. A twin
finish forks the run-in instead — the same two arms, but they stop 0.075 w
either side of a wedge sitting on the throat line, so there are two exits and
the bounce that picks a side is the last thing that happens before the line.
`Stage.twin` in the registry turns it on, the way `gate` turns on the throat,
and it is on every seed of such a stage rather than 72% of them, because it is
what the stage is for. `delta` is the trial stage that shows it
(`--stage delta`): chutes, bumpers and pegs, so the field arrives bouncing
rather than sorted.

Three numbers hold it up, and each one is a lesson already in this file. Each
exit is 94 px centre to centre, 80 px clear of both wall thicknesses, against a
`marble_room` of 72 px and a biggest marble of 57 px — the throat's own
clearance, twice over. The divider is a short cap tilted at 0.4 with flanks at
1.8–2.3, because the cascade measured both ways of getting a divider wrong: a
flat cap is a ledge a marble rests on, a bare point is an apex it balances on.
And it is one solid body rather than three thin edges, because the gauntlet's
wall wedges were edges first and a pinched marble tunnelled inside one.

Nothing in the winner arithmetic had to change. The winner is whatever crosses
y = 110 first, which is a line across the whole frame and asks nothing about x;
the wedge's base stops at y = 192, so both exits empty into the same 82 px of
open frame above the line and neither can be a dead end. Over 48 seeds, 47
marbles left by the left exit and 43 by the right — a fork, not a preference.

**The marbles are nearly the same size now.** The spread was ±12%, with a
comment saying identical marbles keep their starting order and never
overtake. Measured at four spreads, that is not what happens: identical
marbles change the lead *more* often, not less. What the spread was actually
doing was deciding the race before it started — the smallest marble won 60%
of zigzags against a 33% chance, because a smaller marble is quicker through
everything. It is ±6% now, which halves that bias.

Two caveats worth keeping in view. Twenty seeds a stage is enough to see a
50% → 20% move and not enough to argue about five points. And the cascade is
the weakest stage by a distance — one lead change, the half-way leader wins
almost every time — because marbles pick a side at the first peak and keep
it. It ships at a low weight and wants redesigning rather than reweighting.

## ASMR: coins, not a race

`asmr/coin_pour` and `asmr/coin_stack` are the HODL Tales format, and they
invert the priorities: the sound is the product and the picture serves it.

- **Timbre.** A coin is a thin metal disc, so it rings on the inharmonic modes
  of a free circular plate (1, 1.59, 2.14, 2.30, 2.65, 3.16) and rings 0.80 s
  against a marble's 0.26 s. That lives in `audio.TIMBRES`; the marble voice
  is untouched, because the loudness constants were swept against it.
- **Pacing.** A coin already ringing does not answer the next nudge with a
  fresh strike, so each one has a 0.14 s refractory period and a settled pile
  is put to sleep. Without it the pour ran at 74 hits a second, which measures
  louder and is gravel. It now runs at 6–9, and the stack at under 2, with
  1–2 s of silence between coins.
- **No caption, and nothing about price.** The clip shows discs stamped with
  the Bitcoin symbol falling into a vessel. It says nothing about what one is
  worth, and the result-language gate does not apply to it, because a clip
  with no race has no result to give away.
- **The mark is drawn, not typed.** Every font on this machine answers U+20BF
  with the .notdef box — measured, byte-identical to what it gives a Thai
  character — so the ₿ is strokes.

**What the seed must vary, and why it is not coin count.** The sameness gate
is an 8×8 average hash per frame: it sees which of 64 cells are brighter than
that frame's mean. Coin count and tint move no cell at all. The first version
varied only those and scored 0.92 and 0.98 against a 0.88 ceiling over eight
seeds — every clip after the first would have been rejected. What moves cells
is the room's brightness (light backdrops as well as dark, which inverts every
cell at once), where the vessel sits, how much of the frame it covers, its
shape (bowl, flat, vee) and, for the stack, whether there are one, two or
three towers. With those, 10 of 12 seeds clear the ceiling within a variant.

## Themes

A theme is colours, marble names, a caption colour and a decoration, with an
optional window in the calendar. Settings → Themes edits them. The active
theme is whatever is forced there; else the theme whose window contains today;
else the default. Nothing else in the factory knows what month it is.

Marble names matter beyond looks: they appear in descriptions, facts and
titles — "the gold marble reaches the bottom first" — so a theme's names are
words a viewer would use, and a colour that vanishes against its backdrop is
not offered.

Decorations are a few dozen particles behind the marbles — snow, embers,
sparks, drops — deterministic from the seed so a re-render matches. They never
touch the physics.

Shipped: Default, Halloween (Oct 15–31), Christmas (Dec 1–26), New Year
(Dec 27–Jan 3), Valentine (Feb 7–14), Songkran (Apr 10–16).

## Ball battle (`battle/ball_battle`)

The marble race asks *which one gets out first*; the arena asks *which one
is left*. Four balls named by colour bounce in a round arena with a health
bar each across the top of the frame. Every collision costs both balls
health, scaled by the impulse and by weight (a heavier ball shrugs off
more), a ball at zero pops out, and the clip ends a moment after one
remains. Under a third of health a ball goes into **rage** — faster, and
hitting half again as hard — which is what makes a comeback possible and
the viewer's pick matter to the end. No gravity; direction is physics, the
speed is held so the arena never runs down.

Drawn with pygame (headless) rather than PIL: glows, anti-aliased discs,
rounded bars, a burst on elimination. Captions come from `[overlay]
ball_battle` in config, one per seed. Facts carry `winner`, `finishes` and
`eliminated` (the knockout order), so the spoiler gate applies exactly as
it does to a race. `fighters` and `background` are accepted as task
parameters.

## Stuck-marble lessons, round three (gauntlet and rockers)

Measured on 2026-09-22 over 12 seeds each, after the Team screen showed
both stages ending with marbles that never arrived.

**Gauntlet.** Non-finishers were not slow, they were gone: positions like
x = −15 frame-widths, y = 22 frame-heights. The lane-wide gates left a 38 px
pocket beside each bar, less than a marble, and the sweep pinched marbles
against the wall and threw them out of the top of the frame, which had no
ceiling. Three changes: a ceiling on every stage and a speed clamp
(`MAX_SPEED`) so a pinch is a hit, not a launch; a solid wedge on each lane
wall at every bar's height, apex just below the bar, so the pocket does not
exist and the only way down is through the sweep; and the side pegs that
sat under the tips moved to the centre. Parked marbles went from 10 in 27
to 1 in 32. Two more findings on the way: the bar at 0.70 h sat exactly
where the funnel dumps the field, and juggled it for a whole clip (seed
9212 never got a marble past it), so the rows now stop at 0.60; and gate
speed decides the finish — 0.7–1.1 rad/s never stalled but the field came
through one at a time, 1.1–1.6 gave photo finishes and two stalls, and
1.0–1.5 gave both, with a runner-up on 8 of 18 seeds and no stalls.

**Rockers.** Marbles sat at x = 0.06 w, jittering between a plank tip and
the wall, or rocked on a pivot with the plank. Plank tips now keep a
marble's width from the walls, the pivot hub is a real peg so nothing
rests on it, and a short deflector on each wall under every row turns a
thrown marble back to the middle. Runner-ups went from 0 in 6 to 7 in 12.
