# Season 0: the editorial companion

`channels/main/season/s0.yaml` is Season 0 as data: 100 levels, one Short a
day from 2026-09-25 to 2027-01-02. This file is the part of the editorial plan
that is not data: who the marbles are, how copy is written, the long-form
schedule, what is blocked and why, and every place the plan was rewritten on
its way into the season file.

The plan it came from (`02-season0-plan.md` in the Gravity Lab handoff) was
written before any race ran. `docs/08-series-layer.md` wins where they
disagree, and two of its rules decided most of the conversion:

- **2.4, results are never chosen.** `story.must` and `story.prefer` use only
  mechanism predicates (`margin_s`, `lead_changes`, `any_event`, `no_event`,
  `finishers`, `rounds`). No level says who wins, ranks or falls. A beat that
  needed a result was rewritten; see the rewrites list at the end.
- **2.5, no literal numbers.** No copy hint has a digit outside a
  placeholder. Standings and records come in as `{standing:<id>}` and
  `{h2h:<a>:<b>}`; the field size as `{entrant_count}`. Hints never use
  `{margin_s}` or `{lead_changes}`: those are this race's result, and a hint is
  written before the race.

## Status at a glance

| world | levels | ready | blocked | needs input | WP7 due (3 days before first level) |
|---|---|---|---|---|---|
| foundations | L01–L10 | 10 | 0 | 0 | none: existing stages |
| trapdoor | L11–L20 | 0 | 10 | 0 | Oct 2 |
| polarity-swap | L21–L30 | 2 | 8 | 0 | Oct 13 (L22) |
| halloween-maze | L31–L40 | 2 | 7 | 1 | Oct 22 |
| ice-sand | L41–L50 | 0 | 9 | 1 | Nov 1 |
| dice | L51–L60 | 0 | 10 | 0 | Nov 11 |
| arena | L61–L70 | 0 | 10 | 0 | Nov 21 |
| repel | L71–L80 | 0 | 10 | 0 | Dec 1 |
| colour-gates | L81–L90 | 0 | 10 | 0 | Dec 11 |
| grand-final | L91–L100 | 0 | 8 | 2 | Dec 22 (L92 needs the World 4 maze) |
| **total** | | **14** | **82** | **4** | |

Blocked wins over needs-input: a blocked level that also waits on the
operator carries both `blocked_on` and `operator_input`.

## Persona sheet

Colours and traits live in `channels/main/cast.toml`; the balance gate
(every regular wins 10–45% over 48 seeds) decides the trait values, not this
sheet. `bio` is prose for the copy brain.

| id | colour | debut | trait | story role | scores |
|---|---|---|---|---|---|
| blaze | red `#E84C4A` | L01 | fastest off the line, crashes under pressure | the overconfident favourite | yes |
| tide | blue `#378ADD` | L01 | slowest start, never leaves the racing line | the grinder | yes |
| volt | yellow `#F2C230` | L01 | erratic: wins or wipes out spectacularly | the wildcard | yes |
| moss | green `#97C459` | L01 | average speed, uncanny luck | the underdog fans root for | yes |
| nova | purple `#967AE0` | L51 | unknown mid-season challenger | the disruptor | yes |
| ember | orange `#EF8A27` | L71 | heavy, immune to magnets and wind, weak on ramps | the late-season tank | yes |
| ghost | white `#E8E8F0` | L35 | a Halloween-week guest that blocks | guest, L35 only | no |
| acorn | brown `#8C5A2E` | L63 | Harvest Cup guest | guest, L63 only | no |
| juniper | teal `#1FA89A` | L63 | Harvest Cup guest | guest, L63 only | no |

A role is how a marble is introduced, never a promise about how it does. The
copy may say Blaze is fast off the line (that is a trait); it may not say
Blaze keeps crashing unless the standings placeholder says so.

## Copy conventions, as the channel uses them

These reconcile the plan's formulas (its §A4) with docs/08 §4 "Copy". The
season file holds hints; the copy brain proposes, the validator decides.

**Title.** Sentence case, never all caps. At most 70 characters, and the first
45 must stand alone, because the feed cuts there; every title in s0 fits in
45. A search keyword from the season's list (`Marble Race`, `Marble Run`,
`Elimination Race`, `Pick a Color`, `Marble Tournament`) in the first three
words is **preferred, not required**: it ranks candidates, it does not reject
them. No two titles share their first four words. A title **names every
entrant of the level or none of them**: "Blaze vs Tide marble race" is fine
for a two-marble race, "Can Blaze hold the lead?" in a four-marble race is
not, because a title naming one marble passes only when that marble lost.
The same rule holds for the hook, the description line and the pin in the
hints, which is why most hints describe the mechanism rather than a persona.

**Hook.** Six words at most, on screen at frame 0, no result words.

**Description.** Line 1 is the stake in plain English. Line 2, where the level
has one, is standings or a head-to-head, only through placeholders. Line 3 is
the season's fixed footer (`footer:` in s0.yaml), which has no digits:

> Original physics simulation & sound. New race daily. Full tournaments every Sunday. Season standings in the pinned comment.

**Hashtags.** `#shorts` plus three: two broad (`#MarbleRace`, `#Satisfying`,
`#ASMR`, `#OddlySatisfying`) and one niche (`#PickAColor`,
`#EliminationRace`, `#MarbleRun`, `#MarbleTournament`); seasonal weeks may
swap a broad tag for `#Halloween` or `#Christmas`. That is four tags in all,
inside the 3–5 that `rules.md` allows.

**Pinned comment.** Always asks for a choice. `pin_type` in each level rotates
through: `pick_color`, `predict_outcome`, `predict_trap`, `either_or`,
`vote_track`, `rate_chaos`, `rank`, `name_racer`, `rematch_vote`, `call_it`
(ten patterns; the plan asked for at least eight). No two pins repeat. Vote
words are quoted in lower case ("comment \"left\" or \"right\"") rather than
shouted. Persona-voice replies in the first two hours are operator work
(docs/08 §7); nothing here posts.

**Numbers in words.** A structural count that is part of the level's design
("two of each color", "three trapdoors", "seeds four and five") may be spelled
out; a count that is a result may not appear at all.

## Long-form schedule (Sundays)

From the plan's Part C. Tournaments and recaps are rendered from traces by
`factory longform` (WP8), never concatenated. **Every sleep/study entry is
flagged: not built until the policy question in docs/08 §7 is settled**
(looping levels for one to three hours is the pattern the
repetitive-content policy is most likely to catch).

| date | kind | working title | status |
|---|---|---|---|
| Sep 27 | sleep/study | Marble races to study to: Season 0, week one (one hour) | **flag: not built (§7)** |
| Oct 4 | tournament | Week One Cup: the full bracket with slow-motion replays | `--kind tournament`, L01–L10 |
| Oct 11 | sleep/study | Trapdoor marble runs for sleep, no talking | **flag: not built (§7)**; World 2 is blocked anyway |
| Oct 18 | tournament | Trapdoor gauntlet: the full elimination | needs World 2 (blocked) |
| Oct 25 | recap | Season 0 so far: every rivalry explained | `--kind recap`; rivalries come from results, not from the plan |
| Nov 1 | tournament | Halloween Cup: complete replay | needs World 4 (mostly blocked) |
| Nov 8 | sleep/study | Ice and sand marble races for studying | **flag: not built (§7)** |
| Nov 15 | tournament | Ice vs sand final and a newcomer's arrival | needs World 5 (blocked) |
| Nov 22 | recap | ~~The loaded dice investigation~~ → dice week recap | the investigation arc was dropped (L56, L59) |
| Nov 29 | tournament | Harvest Cup: the arena, full replay | needs World 7 (blocked) |
| Dec 6 | sleep/study | Arena marble races to sleep to | **flag: not built (§7)** |
| Dec 13 | tournament | Repel race final and Grand Final seeding explained | needs World 8 (blocked) |
| Dec 20 | recap | Road to the Grand Final: every finalist profiled | `--kind recap` |
| Dec 27 | sleep/study | Snow marble races for Christmas week | **flag: not built (§7)** |
| Jan 3 | tournament | Season 0 Grand Final: the complete replay | needs World 10 (blocked) |

Plan durations (25, 30, 40, 60 minutes; one to three hours) are left out of
the titles: a long-form's length is whatever the traces add up to, and the
title should not promise a number the render did not produce. The plan's
monetisation target (1,000 subscribers + 8,000 hours) is not used as a target
until checked against YouTube's own page (docs/08 §7).

## How the plan mapped onto code

- **World 1 is fully ready** on stages that pass `docs/06`: L01 zigzag, L02
  rapids, L03 funnels, L04 spillway, L05 quarry, L06 seesaw, L07 rapids
  (declared rematch of L02), L08 pinball, L09 gallery, L10 delta. Each level's
  `note` says what was approximated (no gap jump, no hairpin, no straight).
- **Also ready:** L21 and L29 on lodestone (magnets that pull off line; L29 is
  a two-marble head-to-head), L35 on pinwheel (the Halloween guest; the level
  is about the guest, not the maze), L40 on zigzag (a sprint).
- **Needs input:** L39 and L49 (fan-voted obstacle: the operator picks the
  passing stage nearest the winning idea), L91 and L97 (bracket seeds).
- **Laps are rounds.** L17 and L27 carry `rounds: 2`, L45 and L98 `rounds: 3`
  (the sandbox runs at most two, so both wait on WP7 as well). Every ready
  level runs the config default of two rounds (heat and final).
- **Teams** (L11, L12, L17, L20, L65) list the colours as entrants and say in
  `note` that two or three bodies per colour and team scoring are needed.
- **Brackets** (L89–L98) never name marbles: `operator_input: {seeds: null}`
  and empty entrants. The plan's eight-seat bracket cannot be filled from a
  six-marble cast; the operator decides byes or guests before L91.
- **Arena** levels (L61–L70, L77, L94) use `generator: battle`,
  `variant: ball_battle`, format `last_standing` (L62 king of the hill:
  `score`), because WP7 extends the battle generator.
- **Rematches:** L07 → L02 and L92 → L37, both declared; no other level repeats
  a stage with the same field within ten levels. Consecutive levels differ in
  at least two of stage/section, field, format and `must`; in World 1, where
  the field and format never change, each level's `must` was chosen to differ
  from its neighbours' and to fit the stage (a close finish for the rematch,
  every marble home for the no-moving-parts speed test, several lead changes
  for the bumper field).

## Blocked levels by world

`season plan` refuses these until the named WP7 mechanic passes stage QA.
"Base" is the existing stage the section would be added to, where there is
one; trapdoor exists but fails QA today (lead changes 1.4).

| level | date | world | needs | base |
|---|---|---|---|---|
| L11 | Oct 05 | trapdoor | hidden-timer trap mode, elimination format, two marbles per colour (teams) | trapdoor |
| L12 | Oct 06 | trapdoor | three staggered trapdoors in sequence, elimination format, teams | trapdoor |
| L13 | Oct 07 | trapdoor | finish-line trapdoor mode | trapdoor |
| L14 | Oct 08 | trapdoor | fake (painted) trap panels, elimination format | trapdoor |
| L15 | Oct 09 | trapdoor | leader-sensor trap (opens under whoever leads at halfway) | trapdoor |
| L16 | Oct 10 | trapdoor | spiral bowl draining into a centre trapdoor, reverse scoring (last in wins) | — |
| L17 | Oct 11 | trapdoor | team relay (tag at a halfway gate, a trapdoor per leg), teams | trapdoor |
| L18 | Oct 12 | trapdoor | trapdoor countdown drawn on screen | trapdoor |
| L19 | Oct 13 | trapdoor | five-trapdoor track | trapdoor |
| L20 | Oct 14 | trapdoor | seven-trapdoor gauntlet, elimination to one, three marbles per colour (teams) | trapdoor |
| L22 | Oct 16 | polarity-swap | magnet flip_at (attract, then repel) | lodestone |
| L23 | Oct 17 | polarity-swap | magnets on both walls (tug of war) | lodestone |
| L24 | Oct 18 | polarity-swap | repelling magnet behind the finish line | lodestone |
| L25 | Oct 19 | polarity-swap | rotating magnet arm | lodestone |
| L26 | Oct 20 | polarity-swap | shielded lane vs magnet lane (lane split with a field-free side) | lodestone |
| L27 | Oct 21 | polarity-swap | magnet layout mirrored between rounds | lodestone |
| L28 | Oct 22 | polarity-swap | clump-and-release magnet (the current force law cannot hold a marble) | lodestone |
| L30 | Oct 24 | polarity-swap | composite final: attract, flip, rotating arm, reverse finish | lodestone |
| L31 | Oct 25 | halloween-maze | maze with dead ends (a dead end is out), elimination format | — |
| L32 | Oct 26 | halloween-maze | blackout (fog) render effect mid-race | tumble |
| L33 | Oct 27 | halloween-maze | rolling obstacles (pumpkins that roll when hit) | pinball |
| L34 | Oct 28 | halloween-maze | cobweb slow strip (terrain friction on the leader), elimination format | — |
| L36 | Oct 30 | halloween-maze | coffin trapdoor (trap mode), elimination format | trapdoor |
| L37 | Oct 31 | halloween-maze | composite final: maze, blackout, rolling pumpkins, cobweb, coffin trapdoor | — |
| L38 | Nov 01 | halloween-maze | maze with dead ends, solo run (one entrant) | — |
| L41 | Nov 04 | ice-sand | terrain friction sections (ice half, sand half) | — |
| L42 | Nov 05 | ice-sand | alternating ice and sand stripes | — |
| L43 | Nov 06 | ice-sand | ice ramp launch into a sand landing zone | — |
| L44 | Nov 07 | ice-sand | soft sand pit (friction trap) at halfway | — |
| L45 | Nov 08 | ice-sand | ice that melts between rounds, and three rounds (the sandbox runs at most two) | — |
| L46 | Nov 09 | ice-sand | thin ice that cracks at random under weight, elimination format | — |
| L47 | Nov 10 | ice-sand | sand dunes (hidden hills in the floor) | — |
| L48 | Nov 11 | ice-sand | ice bowl with a sand exit chute | — |
| L50 | Nov 13 | ice-sand | terrain gauntlet composite, plus a non-racing purple marble on the sidelines | — |
| L51 | Nov 14 | dice | dice gate (seeded choice of one of three paths) | — |
| L52 | Nov 15 | dice | dice-set random start grid | — |
| L53 | Nov 16 | dice | dice removes one obstacle per run | — |
| L54 | Nov 17 | dice | three dice gates on one track | — |
| L55 | Nov 18 | dice | dice-set round count, one to three (the sandbox runs at most two) | — |
| L56 | Nov 19 | dice | dice gates forced to the hardest path | — |
| L57 | Nov 20 | dice | dice-rolled surface per section (needs the ice-sand sections) | — |
| L58 | Nov 21 | dice | dice-picked handicap (one marble starts early) | — |
| L59 | Nov 22 | dice | handicap: one named marble starts from the back with no dice help | — |
| L60 | Nov 23 | dice | composite final: dice paths, rounds, surfaces and grid | — |
| L61 | Nov 24 | arena | shrinking walls, last one standing | — |
| L62 | Nov 25 | arena | centre hill, king-of-the-hill scoring | — |
| L63 | Nov 26 | arena | shrinking arena with trapdoors, seven entrants | — |
| L64 | Nov 27 | arena | pusher walls that shove marbles into a pit | — |
| L65 | Nov 28 | arena | team arena (a team survives while either marble is alive), teams | — |
| L66 | Nov 29 | arena | ice floor in the arena (needs the ice-sand friction) | — |
| L67 | Nov 30 | arena | centre magnet in a shrinking arena | — |
| L68 | Dec 01 | arena | one-on-one sudden-death arena | — |
| L69 | Dec 02 | arena | arena built to a fan-voted shape | — |
| L70 | Dec 03 | arena | mega arena: walls, pushers and trapdoors, ten bodies | — |
| L71 | Dec 04 | repel | pairwise marble repulsion | — |
| L72 | Dec 05 | repel | one-marble-wide corridor with repulsion | — |
| L73 | Dec 06 | repel | repulsion switched on at halfway | — |
| L74 | Dec 07 | repel | repulsion with one heavy blocker in a lane | — |
| L75 | Dec 08 | repel | pairwise repulsion on the pinball stage | pinball |
| L76 | Dec 09 | repel | pairwise attraction (slipstream) | — |
| L77 | Dec 10 | repel | repulsion inside the shrinking arena (needs WP7 arena) | — |
| L78 | Dec 11 | repel | two lanes merging into one with repulsion | — |
| L79 | Dec 12 | repel | repulsion gauntlet, elimination format | — |
| L80 | Dec 13 | repel | full repulsion track with three ramps | — |
| L81 | Dec 14 | colour-gates | gate that opens for one random colour (per-entrant collision filter) | — |
| L82 | Dec 15 | colour-gates | three colour gates in sequence | — |
| L83 | Dec 16 | colour-gates | gate that closes for the leader's colour | — |
| L84 | Dec 17 | colour-gates | gate that opens for two random colours | — |
| L85 | Dec 18 | colour-gates | gate cycling through every colour | — |
| L86 | Dec 19 | colour-gates | colour gate that drops the wrong colours through a trapdoor, elimination format | trapdoor |
| L87 | Dec 20 | colour-gates | colour gates on an ice floor (needs ice-sand friction) | — |
| L88 | Dec 21 | colour-gates | breakable colour gate with a penalty rule for heavy marbles | — |
| L89 | Dec 22 | colour-gates | cycling gate on the seeding track | — |
| L90 | Dec 23 | colour-gates | composite final: random, reverse, cycling and trapdoor gates on snow | — |
| L92 | Dec 25 | grand-final | maze with dead ends (reused from World 4) | — |
| L93 | Dec 26 | grand-final | dice gates (reused from World 6) | — |
| L94 | Dec 27 | grand-final | shrinking arena (reused from World 7) | — |
| L95 | Dec 28 | grand-final | composite gauntlet: magnets, ice, colour gates | — |
| L96 | Dec 29 | grand-final | composite gauntlet: trapdoors, repulsion, dice gates | — |
| L98 | Dec 31 | grand-final | composite of every world's sections, three rounds | — |
| L99 | Jan 01 | grand-final | solo lap through every world with a season standings overlay | — |
| L100 | Jan 02 | grand-final | teaser scene: track under construction and a new marble's silhouette (not a race) | — |

## Ready and needs-input levels

| level | status | stage | needs input | note |
|---|---|---|---|---|
| L01 | ready | zigzag | — | gap jump -> zigzag; no gap-jump section exists, the drop from one ramp to the next is the nearest thing. |
| L02 | ready | rapids | — | hairpin turn -> rapids; no hairpin section, the stage's opening ramps switch back before the chutes. |
| L03 | ready | funnels | — | funnel start, collide at the exit -> funnels (stacked funnels, every throat a bottleneck). |
| L04 | ready | spillway | — | two-lane split that rejoins -> spillway (split-and-rejoin chutes, pegs, funnel); lanes are not chosen, so 'short vs safe path' is not modelled. |
| L05 | ready | quarry | — | five-drop staircase -> quarry: a sieve of bar rows to fall through, then a funnel and pegs; not five discrete steps. |
| L06 | ready | seesaw | — | seesaw obstacle -> seesaw stage (rocking planks, pegs, funnel); planks tip under any marble, not only under two. |
| L07 | ready | rapids | — | declared rematch of L02 (same stage rapids, same four); must a close finish, prefers a photo finish. |
| L08 | ready | pinball | — | bumper field -> pinball (bumpers, rocking planks, funnel); the bumper count is the stage's, not twelve. |
| L09 | ready | gallery | — | long straight sprint -> gallery (pegs, sieve, funnel, nothing kinematic); a falling race has no straight, so 'no traps' means nothing that moves. Must: all four finish. |
| L10 | ready | delta | — | all Week 1 obstacles combined -> delta (trial stage that passes QA: chutes, bumpers, pegs, forked finish); no composite stage exists. Double points come from final: true. |
| L21 | ready | lodestone | — | single attract magnet -> lodestone (trial stage that passes QA): pegs, a band of magnets alternating side to side, pegs. Several magnets, not one. |
| L29 | ready | lodestone | — | Head-to-head on lodestone with two entrants (stage QA measured three to five). The plan picked Moss and Volt from standings for the last final seed; here the pairing is fixed in advance and the seat is this race's stake. |
| L35 | ready | pinwheel | — | The level is about the guest, not the maze: raced on pinwheel (one big wheel among pegs). The ghost scores = false: it can cross first and earns nothing. Public copy avoids its name, which would name one of five entrants. |
| L39 | needs_input | — | stage, fan_idea | Operator picks the passing stage nearest the winning idea, sets params.stage and drops section; if nothing fits, set status blocked. |
| L40 | ready | zigzag | — | 4-way sprint -> zigzag, the fastest stage. The plan's per-world points reset does not exist (standings run all season). |
| L49 | needs_input | — | stage, fan_idea, credit | Operator sets params.stage to the passing stage nearest the winning idea (drop section) and posts the credit; blocked if nothing fits. |
| L91 | needs_input | zigzag | seeds | World 1 track -> zigzag (L01's stage) under the Christmas theme. Seed 1 vs seed 8. Seeds come from standings at plan time; do not hard-code names. A six-marble cast cannot fill the plan's eight seeds, so the operator decides byes or guests. |
| L97 | needs_input | — | seeds, stage | Losers of L95 and L96. Operator sets params.stage to the fan-chosen passing stage (drop section). Seeds come from standings at plan time; do not hard-code names. A six-marble cast cannot fill the plan's eight seeds, so the operator decides byes or guests. |

## Story and copy rewrites

Every place the season file departs from the plan's beats or wording.
"story" rewrites changed what a level is about or who races it, because the
plan's version needed a result to have happened (rule 2.4); "copy" rewrites
removed a digit, a draft number, a claim about a persona's record, or a name
that would make a hint name some entrants but not all. 89 rewrites: 19 story, 70 copy.

| level | kind | plan said | now | why |
|---|---|---|---|---|
| L01 | copy | Title 'before the Gap Jump'; 'Season 1 opener — everyone starts at 0 points' | 'before the drop'; 'Season opener: everyone starts level on points' | No gap jump on the stage; digits removed (and this is Season 0, not 1). |
| L02 | story | 'Blaze won the opener by a nose… Blaze hates corners'; title 'Can Blaze Hold the Lead?'; 'Standings: Blaze 3, Moss 2, Tide 1, Volt 0' | question about whoever leads at the first ramp; standings as {standing:<id>} for all four | Rule 2.4: L01's result is not chosen; a title naming one of four marbles is barred; rule 2.5 digits. |
| L03 | copy | Title '…One Survives'; 'Head-to-head so far: Blaze 2–0 vs Volt' | 'Pick a color: funnel start chaos'; head-to-head line dropped | Every marble finishes, so 'one survives' is false; the h2h line was a draft result and named two of four. |
| L04 | copy | 'Left lane is shorter but has a drop… Tide always goes safe'; 'Standings after 3: Blaze 7, Moss 4, Volt 3, Tide 2' | chutes split and rejoin, the bounce picks; standings placeholders | No lane choice exists and no marble 'always' does anything yet; draft numbers. |
| L05 | story | 'Moss vs the Staircase Drop'; 'Moss has never led a single race'; 'Moss's record: 0 wins, 3 top-two finishes'; pin 'Predict Moss's finishing position 1–4' | an underdog race about the drops, no persona named; pin asks for the whole order | Moss's record is whatever L01–L04 produced; a title naming one of four is barred; digits. |
| L06 | copy | 'A seesaw that only tips when two marbles land on it'; 'Tide's slow start might finally pay off' | planks tip under a marble's weight; persona line dropped | The stage's planks tip under one marble; 'finally' presumes earlier results. |
| L07 | story | 'L02 ended in a measurement so close we're running the hairpin again'; title 'Blaze vs Moss Photo Finish'; 'Blaze 12 vs Moss 11' | rematch declared up front; the close finish is a story must (margin_s <=0.5); no persona named | L02's margin and podium are not chosen; the rematch reason must hold whatever L02 produced. |
| L08 | copy | '12 Bumpers'; 'Volt thrives in chaos'; 'Volt's wins so far: 1, all of them ridiculous'; pin 'Rate 1–10… at the 5-second mark' | no counts; persona line dropped; 'halfway through' | Digits and a draft win count. |
| L09 | copy | 'This is Blaze's home turf'; 'Fastest recorded run: Blaze, 3.1 s' | stage description only | Draft record and a claim about one persona. |
| L10 | copy | 'Gap, hairpin, seesaw, bumpers, all in one track'; 'Standings going in: Blaze 15, Moss 13, Volt 8, Tide 6'; 'Full 25-minute bracket' | what delta actually has; standings placeholders; no duration | No composite stage; draft numbers. |
| L12 | copy | 'Team standings: Green 5, Blue 4, Red 3, Yellow 2' | dropped | Draft numbers; team scoring does not exist yet. |
| L13 | story | 'Blaze has fallen into every trapdoor so far'; pin 'Blaze is 0-for-3 on trapdoors' | no persona record; pin asks who reads the door | Docs/08 §9 and rule 2.4: L11–L12 cannot be made to catch Blaze; the handoff's eliminated_includes chain is not used. |
| L14 | copy | 'Tide is quietly second on the team board'; pin 'comment two numbers between 1 and 6' | standings placeholders; pin without numbers | Draft standing; digits. |
| L16 | copy | 'Volt finally has a format that rewards flailing' | dropped | Presumes Volt's earlier results; names one of four. |
| L17 | copy | 'Team Green has yet to lose a relay' | dropped | This is the first relay; the claim is a draft result. |
| L18 | copy | 'Fan request from the L12 comments' | dropped | Unverifiable claim; digits. |
| L19 | story | 'Blaze has never beaten Tide on a trapdoor track'; 'Head-to-head on trapdoor tracks: Tide 3–0' | 'Head-to-head so far: {h2h:blaze:tide}' | Rule 2.4: the grudge match is declared; its history is whatever happened. |
| L20 | copy | 'Team board going in: Green 22, Blue 20, Red 15, Yellow 14' | standings placeholders | Draft numbers. |
| L21 | copy | 'Ember (Orange) hasn't arrived yet, so everyone is vulnerable'; pin 'pulled in' | dropped; 'pulled off line' | Names a marble not in the race; the stage's magnets deflect, they cannot hold a marble. |
| L22 | copy | 'Moss's luck stat is about to be tested' | dropped | Names one of four. |
| L23 | copy | 'Volt's wobble might actually help here' | dropped | Names one of four. |
| L24 | copy | 'Blaze finally has a mechanic that rewards speed' | dropped | Names one of four; 'finally' presumes results. |
| L25 | copy | 'every two seconds'; 'Tide's rhythm vs Blaze's speed, again' | 'on a steady beat'; dropped | Number; names two of four. |
| L26 | copy | 'Moss picks by luck as always' | dropped | Names one of four. |
| L27 | copy | 'Two Lap'; 'First multi-lap race of the season' | 'Two round'; dropped | Laps are rounds; every race already runs two rounds by default, so 'first' is false. |
| L28 | copy | 'Pure chaos, Volt's favorite' | dropped | Names one of four. |
| L29 | story | 'Only one of them makes the World 3 Final' (standings-driven qualifier); 'Season head-to-head: Moss 2, Volt 2' | fixed pairing whose winner takes a final seat; '{h2h:moss:volt}' | Rule 2.4: who needs a qualifier depends on results that have not happened. |
| L30 | story | 'World 2 champion has a bye; this decides the second Grand Final seat' | finalists from operator_input | Who has a bye depends on results. |
| L31 | copy | 'Three Dead Ends'; 'Cup format: 7 rounds, points carry to the Oct 31 final' | no counts; 'points carry to the final on Halloween night' | Digits. Cup points are season points: the code keeps one table. |
| L32 | copy | 'Two Seconds of Total Darkness'; 'Cup standings after R1: Tide 5, Moss 3, Blaze 2, Volt 0' | 'lights out mid-race'; season standings placeholders | Digits and draft numbers. |
| L33 | copy | 'Blaze leads into every pumpkin and eats every one' | dropped | A result claim about one persona. |
| L34 | copy | 'Cup standings after R3: Tide 12, Moss 10, Volt 6, Blaze 5'; pin 'Should Blaze slow down on purpose?' | standings placeholders; 'Should the leader…' | Draft numbers; names one of four. |
| L35 | copy | Title 'Ghost Marble Race: A Fifth Racer That Can't Win' | 'Fifth racer marble race: a guest joins'; 'can't score' | The guest can cross first; it only cannot score. Naming it alone would name one of five entrants. |
| L36 | story | 'Standings: Tide 19, Moss 17, Volt 11. Blaze is out.' | entrants from operator_input; standings line dropped | Rule 2.4: who reaches the semifinal is a result. |
| L37 | copy | 'Fog, pumpkins, cobwebs, ghost, coffin'; 'Watch the 30-minute cup replay on Sunday' | ghost dropped; no duration | The guest leaves after L35 in the cast; digits. |
| L38 | story | 'Blaze redemption run… Eliminated early, Blaze runs the maze alone against the champion's time'; pin 'OVER or UNDER' | bottom-of-the-table marble from operator_input; no target time | Rule 2.4: Blaze being eliminated is a result; the champion's time is not a placeholder. |
| L39 | copy | 'gets built in World 5' | 'next world' | Digit. |
| L40 | story | 'Season Reset: New Points'; 'World 5 starts with fresh points'; 'Seats so far: World 2 champ, World 3 champ, Halloween champ' | a checkpoint with standings placeholders | Standings are season-long in code; the seat list depends on results. |
| L41 | copy | 'Ice is Blaze's, sand is Tide's' | dropped | Names two of four; presumes results. |
| L42 | copy | 'Eight stripes'; 'Volt's wobble gets worse on ice'; pin 'Count the stripes' | no count; dropped | Number; names one of four. |
| L43 | copy | 'Moss's luck vs physics' | dropped | Names one of four. |
| L44 | copy | 'Leader-trap week continues, and Blaze still hasn't learned' | dropped | Result claim about one persona. |
| L45 | copy | 'Three Lap'; 'Lap 3 is slush'; 'First 3-lap race; endurance favors Tide' | rounds; 'the last round'; dropped | Laps are rounds; digits; names one of four. |
| L46 | story | 'Two marbles fall through every run'; pin 'Two fall through. Name both colors.' | no fixed count; 'who falls through first' | How many fall is a result; the story must only requires that someone is caught. |
| L49 | copy | Pin 'This obstacle came from @[winner]' | credit is operator_input.credit, posted by the operator | Not a known placeholder; the validator only fills measured values. |
| L50 | copy | 'Seats locked: 4 of 8'; pin 'Name it, best name debuts next world' | dropped; 'Friend or threat?' | Digits; the newcomer's name is fixed in the cast, so a naming vote would be false. |
| L51 | copy | Title 'New Marble Nova Debuts…' | 'New marble debuts on the dice track' | Names one of five entrants. |
| L52 | story | 'Blaze starts last for the first time ever'; 'Nova's debut result: mid-pack'; pin 'Blaze from last place' | whoever draws the back; no debut result | Rule 2.4: the draw is seeded, not chosen; L51's result is unknown. |
| L53 | copy | 'Nova posts the fastest split so far' | dropped | Draft result. |
| L54 | copy | 'Nova might be faster than Blaze'; 'Blaze's first head-to-head against a newcomer' | h2h placeholder | Speculation about results; the two have met in L51–L53. |
| L55 | copy | 'Random Lap Count: One, Two, or Three'; 'Tide has never lost a 3-lap race' | rounds; dropped | Laps are rounds; draft result; digit. |
| L56 | story | 'Someone tampered with the die. Standings reveal who benefited. The investigation runs through L60'; pin 'Who rigged the die? Accuse a color.' | a fixed hard-path episode, no tampering arc | The arc's culprit would come from standings (a result) and accuses a persona of cheating on a channel whose promise is a fair race. |
| L57 | copy | 'Moss's luck stat now has a stage'; pin 'Guess a number 0–4' | dropped; no range | Names one of five; digits. |
| L58 | copy | 'a full second early'; 'Fairness experiment requested in the comments' | 'early'; dropped | Number; unverifiable claim. |
| L59 | story | 'Volt Caught Cheating: Penalty Race From Last Place… Standings math pointed at Volt… must finish top two to stay in the final' | the standings leader starts last (operator_input.back_marker) | Rule 2.4 and the dropped L56 arc: the culprit and the stake were scripted results. |
| L60 | copy | 'random laps'; 'Seats locked: 5 of 8 after tonight' | 'random rounds'; dropped | Laps are rounds; digits. |
| L61 | copy | 'Walls Close Every Three Seconds'; '5 arena rounds' | no interval or count | Numbers. |
| L62 | copy | 'Nova vs Tide is now the rivalry to watch' | dropped | A rivalry is a result; names two of five. |
| L63 | copy | 'Eight Marbles'; 'All six personas plus two guest marbles'; 'Sunday: 40-minute cup replay' | '{entrant_count} marbles, two of them harvest guests'; no duration | Ember has not debuted, so the field is seven; digits. |
| L64 | copy | 'Ember (Orange) arrives next world' | 'A heavy newcomer arrives next world' | Names a marble not in the race. |
| L65 | copy | 'Blaze and Volt paired together, chaos squared' | pairs are operator_input; line dropped | Names two of five. |
| L66 | copy | 'Crossover mechanic, fan-requested'; pin 'Rate the chaos 1–10' | dropped; no scale | Unverifiable; digits. |
| L68 | story | 'The season's newest rivalry'; 'Head-to-head: Nova 2, Tide 2'; pin 'Loser drops a seed in the Grand Final bracket' | '{h2h:nova:tide}'; no seeding stake | A rivalry and a record are results; seeding comes from standings, not from an invented rule. |
| L69 | copy | '[shape]'; 'Fan track #3 of the season'; pin '@[winner]' | operator_input shape and credit; dropped | Operator fill-ins; digit. |
| L70 | copy | 'Ten Marbles'; 'Seats locked: 6 of 8. Ember debuts tomorrow.' | dropped; 'A heavy newcomer debuts tomorrow' | Digits; names a marble not in the race. |
| L71 | copy | Title 'New Marble Ember Debuts…' | 'New marble debuts…' | Names one of six entrants. |
| L72 | story | 'Blaze drew pole. Ember drew last.' | dropped | The draw is seeded; it is not known in advance. |
| L74 | copy | Title '…Can Anyone Get Past Ember?'; 'Ember's weakness revealed: terrible on ramps' | 'get past the tank'; 'its bio says it's weak on ramps' | Names one of four entrants; 'revealed' presumes a result. |
| L75 | story | 'Volt's redemption arc begins: penalty served'; pin 'REDEMPTION or RELAPSE' | dropped with the L56–L59 arc | The penalty arc was scripted from results. |
| L76 | copy | 'Tide's patience finally has physics on its side' | dropped | Names one of six. |
| L77 | copy | 'Ember's arena'; 'Crossover requested in the L70 comments' | 'the heaviest marble's kind of arena'; dropped | Names one of six; unverifiable; digits. |
| L78 | copy | 'Blaze vs Nova at the merge, third episode of their rivalry' | '{h2h:blaze:nova}' | Their record is whatever happened; it is their second billed duel. |
| L79 | story | 'Six marbles without a seat… Locked seats: Tide, Moss, Halloween champ, Nova, Harvest champ, World 7 champ' | entrants from operator_input; no seat list | Seats come from results. |
| L80 | copy | Title '…Ember Against Everyone'; 'All 8 Grand Final seats now locked' | 'the heavy one against all'; dropped | Names one of six; digit. |
| L82 | copy | 'Seeding standings: Nova 1st, Tide 2nd' | standings placeholders for all six | Draft result; digits. |
| L84 | copy | 'Blaze and Tide as allies for one race only' | dropped | The gate's pick is seeded, not known; names two of six. |
| L85 | copy | 'all six colors once per second'; 'Rhythm race, Tide's specialty' | 'every color'; dropped | Numbers; names one of six. |
| L86 | copy | 'Elimination version of the gate, 8 marbles'; pin 'Guess a number 1–7' | dropped; no range | Digits; six in the cast. |
| L87 | copy | 'Grand Final: Dec 25, eight marbles, all worlds' | 'The Grand Final is on Christmas Day' | Digits; eight is not the cast size. |
| L88 | copy | Title 'Ember vs the Gate…'; 'Story: Ember's first rule-bending moment' | no name; dropped | Names one of six. |
| L89 | copy | 'All eight finalists'; 'Seed 1 gets to choose' | 'All the finalists'; 'the top seed' | Six in the cast; digit. |
| L90 | copy | Pin 'Bracket is out: [seed list]' | operator_input.seed_list, posted by the operator | Operator fill-in. |
| L92 | copy | 'Full Grand Final on Sunday' | dropped | Kept short; the long-form schedule carries it. |
| L93 | story | 'Seed 2 has never lost to Seed 7' | dropped | A head-to-head is a result and the seeds are not known yet. |
| L95 | copy | 'Winner goes to the Dec 31 final'; 'Head-to-head record… in the description' | 'New Year's Eve final'; dropped | Digits; the semifinalists are not known, so no h2h placeholder can be written. |
| L97 | copy | 'fan track #4 of the season' | dropped | Digit. |
| L98 | copy | 'Ten Worlds, Three Laps'; 'The 60-minute replay' | 'every world', rounds; dropped | Laps are rounds; digits. |
| L99 | copy | 'Every result from L01 to L98'; pin 'Reply with the level number' | 'Every result of the season' | Digits. |
| L100 | copy | 'Season 1 starts Jan 4'; 'a seventh marble'; pin 'canon on Jan 4' | 'starts on Monday'; 'a new marble' | Digits. |

## What the plan asked for that could not be mapped

- **Eight Grand Final seats and seeds one to eight** (L79–L98): the cast has
  six scoring marbles. Seeds are operator input; the operator decides byes or
  guests.
- **"All six personas plus two guests" at L63:** Ember debuts at L71, so the
  Harvest Cup final is five personas plus two guests.
- **Per-world points resets and Cup tables** (L31–L40, L40's "season reset"):
  the code keeps one season table. Copy says "standings".
- **Double points at L89:** only `final: true` doubles, and L89 is not a final.
- **A time trial against another race's time** (L38): no placeholder carries
  a time from a different clip.
- **Fan credit and fan shapes** (L49, L69): `operator_input`, posted by the
  operator; not placeholders.
- **The loaded-dice investigation and Volt's penalty and redemption**
  (L56, L59, L75): dropped rather than rewritten into a result-driven arc.
- **"Last frame matches first"** (plan §A2): dropped in docs/08 §9; a falling
  race cannot loop.
- **L100** is not a race; it waits on a non-race scene.
