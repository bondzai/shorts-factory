# Stages and themes

## Stages

A race needs a descent, and each shape of descent is a different picture to
the similarity gate and a different question to the viewer.

| stage | what the viewer sees | measured (24 seeds, through the retry loop) |
|---|---|---|
| **zigzag** | six to nine full-width ramps, alternating sides — fast, the classic | 24 finish, median 13.7 s |
| **pegboard** | a Galton board: rows of small pegs, nothing to rest on | 24, median 14.2 s |
| **bumpers** | pinball: a lattice of large elastic bumpers, 3–4 spinning bars | 24, median 13.2 s |
| **funnels** | three or four funnels in series, throats offset — every throat a bottleneck | 24, median 13.6 s |
| **gauntlet** | a narrowed lane of 5–6 lane-wide spinning bars: gates, not obstacles | 23, median 14.4 s |
| **cascade** | chutes that split at a tilted peak and rejoin at a V, five or six rows | 24, median 13.1 s |

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
