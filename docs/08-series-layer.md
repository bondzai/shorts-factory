# Series layer: seasons, cast, standings

This replaces the Gravity Lab handoff package of 2026-09-25 (`00-HANDOFF.md`,
`01-series-layer-spec.md`, `02-season0-plan.md`) and every earlier plan it
superseded. Where this file and those disagree, this file wins; the changes
are listed in "What changed from the handoff" at the end.

## 1. What it is for

A channel of one-off clips reads as a template. A season makes each clip an
episode: the same cast, a running table, a reason to watch the next one. That
serves three things at once:

1. YouTube's "generic or repetitive content" policy: consecutive clips differ
   in stage, cast, format or stakes, and the description says what changed.
2. Long-form watch hours: every approved race keeps a trace, and a weekly
   long-form is redrawn from traces, not re-simulated and not concatenated.
3. Any code-rendered channel can use it by adding files, not code.

**Out of scope:** footage or AI video; any LLM in simulation, seeds,
rendering, approval or publishing.

## 2. Ground rules

1. **Extend, never rewrite.** Pipeline, QC, sameness guard, publish drivers,
   themes, console and MCP server stay; the series layer is added beside them.
   A channel with no `season/` folder behaves exactly as before.
2. **Code produces facts, a model produces wording, code checks the wording.**
   No model call in any path that changes pixels, except burning an
   already-validated hook through the existing `rehook`.
3. **No cloud dependency.** Built-in brains run on the `ollama` provider;
   outside agents connect over MCP with no API key.
4. **Results are never chosen.** A story may require that something *happens*
   (a launch, a lead change, a trapdoor catching someone); it may not require
   *who* wins, loses or falls. The channel promises a fair race — "Believed"
   in `prompts/skill-value.md` — and a seed searched until a named marble
   loses is a rigged race with extra steps. `factory season check` rejects
   identity predicates unless `[series] allow_identity_constraints = true`.
   The story follows the results: copy is written from the outcome, and a
   plan beat that needs a particular result is rewritten, not forced.
5. **No literal number in any published text** that is not produced by a
   placeholder filled from a measured outcome.
6. When a level cannot be built as the plan describes, build the nearest
   version and say so in the season file (`note:`); do not improvise story.

## 3. Architecture

| Layer | Existing (kept) | New |
|---|---|---|
| Surfaces | CLI, console, MCP, Telegram | `factory season …`, `factory copy`, `factory longform`; MCP season tools |
| Series | — | `factory/series/`: outcome, trace, cast, season, story, standings, copy check, long-form |
| Pipeline | plan → render → QC → review → publish → metrics | season plan (skips Idea), story check in the seed loop, standings on approve |
| Generators | physics, battle | `GeneratedClip.outcome`, `GeneratedClip.trace_path` |
| Storage | SQLite, `channels/<id>/`, `data/` | `seasons`, `levels`, `results` tables; `clips.trace_path`, `clips.level_id` |

The series package never imports a generator. It reads `Outcome` and traces.
Generators may import the series contracts (`series.outcome`, `series.trace`,
`series.story`, `series.cast`), which import nothing from the factory above
`settings`.

### Per level

season file + cast → story check over seeds (simulation only) → render the
chosen seed → trace + outcome saved → copy: local model proposes, validator
checks, template fallback → QC (existing, incl. sameness) → human approves →
standings updated → publish (existing).

## 4. Contracts

### `GeneratedClip` (factory/generators/base.py)

```python
outcome: Outcome | None = None    # None: not a competition; series features skip it
trace_path: Path | None = None    # data/work/<channel>/<clip>/trace.json
```

### `Outcome` (factory/series/outcome.py)

`Placement(entrant_id, rank, time_s, status)`, `Event(t_s, kind, entrant_id,
data)`, `Outcome(format, placements, margin_s, lead_changes, events, facts)`.
`format` is `race | elimination | last_standing | score`. Ties share a rank.
`status` is `finished | running | stopped | eliminated | out`. Event kinds are
generator-defined; physics emits `lead_change`, `finish`, `trap_catch`,
`launched`, `round_start`, and — from WP7 mechanics (docs/10) — `eliminated`,
`broke` and whatever kinds a world's section names.

### Trace (factory/series/trace.py)

Beside `clip.mp4`: `trace.npz` + `trace.json`.

- `trace.npz` (deterministic zip: fixed timestamps, sorted names):
  `positions` float64 `[frames, entrants, 2]` per round (`round0_positions`,
  `round1_positions`, …), `radii`, `colors` uint8.
- `trace.json`: `schema_version`, `generator`, `variant`, `seed`, `fps`,
  `sim_w`, `sim_h`, `entrant_ids`, `rounds[]` (stage, style without physics
  bodies, segments, winner, winner_frame, impacts, overlay text), `outcome`.
- Redraw needs no pymunk: the generator's `redraw(trace_dir)` feeds the existing
  renderer, so a redrawn frame is the shipped frame.
- Retention: `[retention] trace_days = -1` keeps traces of approved and
  published clips forever; rejected traces go with `rejected_days`.

Positions are float64, not float32 as first specified: float32 moves an
anti-aliased edge by a pixel often enough to break "redraw equals the render".
Marble rotation is not stored because no renderer draws it.

### Cast (`channels/<id>/cast.toml`)

```toml
[[entrant]]
id = "blaze"
name = "Blaze"
color = "#E84C4A"
traits = { friction = 0.18, mass_mult = 0.9 }
bio = "Fastest off the line, crashes under pressure"
debut = "L01"
scores = true
```

Traits physics understands: `mass_mult`, `friction`, `radius_mult`, `jitter`
(small seeded nudge each frame), `force_immune` (magnets and future fields
skip it), `charge` (a marble's share of a pair force, default 1; docs/10).
Unknown traits are logged and ignored. With a cast, entrant colours
override the theme's marble colours; the theme keeps palettes and decoration.
`bio` is for the model and never parsed. `scores = false` marks a guest.

**Balance gate:** over 48 seeds of a live stage, every regular entrant wins
10–45% of races. Traits are nudges, not a script.

### Season (`channels/<id>/season/<season>.yaml`)

```yaml
id: s0
title: Season 0
channel: main
scoring: default
levels:
  - id: L22
    date: 2026-10-16
    world: polarity-swap
    generator: physics
    variant: marble_race
    params: { stage: lodestone }
    entrants: [blaze, tide, volt, moss]
    format: race
    story:
      must:   { any_event: launched }
      prefer: { lead_changes: ">=1", margin_s: "<=0.8" }
    copy:
      angle: "the magnet flips halfway; somebody gets launched"
      title: "Marble Race Polarity Swap: Pulled In, Then Shot Out"
      pin: "Getting launched: good or bad? Predict it before the flip."
      pin_type: predict_outcome
    rematch_of: null
    status: ready            # ready | blocked | needs_input
    blocked_on: null         # e.g. "WP7 magnets: flip_at"
    operator_input: {}       # fields the operator must fill before planning
    note: null
```

Predicates (closed list, no eval): `margin_s`, `lead_changes`, `any_event`,
`no_event`, `finishers`, `rounds`, `eliminations` (how many were taken out,
never which) — and the identity ones `winner_in`,
`winner_not_in`, `rank_of`, `eliminated_includes`, which rule 2.4 keeps out
of a season unless switched on. Comparators are strings: `">=1"`, `"<=0.8"`.

**Anti-repetition, checked on load:**
- consecutive levels differ in at least two of: stage/mechanic, entrant set,
  format, story `must`;
- the same stage with the same entrants within 10 levels only with
  `rematch_of`, at most one per 10 levels;
- every entrant referenced exists in the cast; no entrant appears before its
  `debut`.

### Story check (seed search)

After simulation and before rendering, `story.must` is evaluated on the
`Outcome`; a failure derives the next seed exactly as the stall retry does.
`[series] max_story_attempts = 200`; exhausting them fails the clip as
`story_unsatisfiable` — constraints are never relaxed quietly. `prefer`
scores passing candidates and the best of the first `prefer_pool = 5` is
kept. `story_attempts` and the chosen seed are recorded in facts.

### Standings

Default scoring: race 3/2/1; elimination and last-standing, one point per
entrant outlasted; a level with `final: true` doubles. `scoring.toml`
overrides. Updated when a clip is **approved**, and recomputable from scratch
(`factory season standings --recompute`) so reject/restore cannot drift the
table. Guests (`scores = false`) never score. Head-to-head is derived from
results, never stored.

Ranks are the generator's. A guest keeps its place in the result but earns
nothing, so a regular behind a guest scores by its own rank. In `race` and
`score`, a placement whose status is not `finished` scores 0. A level has one
counted clip: a second clip for the same level cannot be approved until the
first is rejected or binned. Rejecting, binning, destroying or un-approving a
clip (an agent's `rehook` of an approved clip) drops its result, and unbinning
an approved clip records it again.

`channels/<id>/scoring.toml` (every key optional; the defaults are shown):

```toml
final_multiplier = 2        # level `final: true`
finishers_only = true       # race/score: a non-finisher scores 0
[race]
points = [3, 2, 1]          # by rank; ranks past the list score 0
[score]
points = [3, 2, 1]
[elimination]
per_outlasted = 1           # per entrant ranked below (a teammate is not outlasted)
[last_standing]
per_outlasted = 1
[teams]
mode = "sum"                # a team race (`teams:`) scores the persona: "sum" of its marbles, or "best"

# A season with `scoring: cup` uses [scheme.cup] on top of the above.
[scheme.cup]
final_multiplier = 3
[scheme.cup.race]
points = [5, 3, 2, 1]
```

### Copy (title, pinned comment, description line 1, hook)

A text-only local brain (`[llm.agents] copy = "ollama/qwen2.5:3b"`) gets the
outcome **without the winner**, facts, standings, the level's `copy` hints,
cast names and bios, `rules.md`, and the last 30 titles/pins. It returns three
candidates for each field (`CopyProposal`). Measured values reach the text only
through placeholders — `{margin_s}`, `{lead_changes}`, `{entrant_count}`,
`{leader_name}` (standings leader *before* this race), `{standing:<id>}`,
`{h2h:<a>:<b>}` — filled by code.

The validator (`factory/series/copy_check.py`) rejects a candidate that:
1. has a digit not produced by a placeholder, or an unknown placeholder;
2. names the winner or a result (the existing spoiler gate);
3. names some entrants but not all of them — a title that names one marble
   can only pass when that marble lost, and a viewer learns that "the one in
   the title loses" (a matchup naming every entrant is fine);
4. is a title over 70 characters, or whose first 45 do not stand alone;
5. is a hook over 6 words, or has result words;
6. repeats the first 4 words of any of the last 30 titles, or any of the last
   30 pins exactly;
7. is not English.

A search keyword ("Marble Race", "Pick a Color", …) in the first three words
is *preferred* — it ranks candidates — but not required: the Shorts feed is
not search, and "Call it before the wheel does" is a better feed title than
most keyword-first ones. First passing candidate wins; none passing falls
back to the template with standings filled in. Which path was used is logged,
and `factory season status` shows the local-vs-template rate.

The hook is burned only through `rehook` (pixels only, same seed).

### Long-form

`factory longform --levels L01..L10 --kind tournament|recap` renders 1920×1080
from traces: the 9:16 race redrawn in the centre, standings and level in side
panels, a title card per level, `chapters.txt` and a description with the
table. It never concatenates shorts. `sleep` compilations are **not built**
until the policy question in §7 is settled.

## 5. Surfaces

```
factory season check     [--season s0]                 schema, cast, anti-repetition, identity predicates
factory season plan      --levels L01..L10              queue make-clip tasks for those levels (no Idea agent)
factory season standings [--after L20] [--recompute]
factory season status                                    levels, their clips, blocked levels, copy path rate
factory copy             --clip <id> [--brain local|template]
factory longform         --levels L01..L10 --kind tournament|recap
```

MCP (read and build only): `season_check`, `season_plan`, `get_standings`,
`get_level`, `propose_copy`, `submit_copy` (through the same validator).
Telegram approval messages carry the level id and a standings line.

## 6. Work order and status

| # | Package | Status (2026-09-25) |
|---|---|---|
| WP1 | Outcome + trace + redraw (physics) | done |
| WP2 | Cast + traits (physics), `cast.toml` | done |
| WP3 | Season file, `season check`, `season plan`, tables | done |
| WP4 | Story check in the seed loop | done |
| WP5 | Standings on approve, recompute, head-to-head | done |
| WP6 | Copy brain + validator + fallback | done |
| WP9 | CLI + MCP surfaces, Telegram line | done |
| WP8 | Long-form tournament + recap from traces | done |
| WP7 core | The hooks every world uses: elimination, clocks, surfaces, filters and pair forces, 12 entrants and teams, three rounds, render effects, team and elimination standings (docs/10-mechanics.md) | done |
| WP7 | New mechanics per world (trap modes, magnet flips, maze, ice/sand, dice, arena, repulsion, colour gates) | one PR per world, each through stage QA before its levels leave `blocked` |

Season 0's 100 levels are in `channels/main/season/s0.yaml`. World 1 uses only
stages that pass `docs/06` today. Levels needing a WP7 mechanic are
`status: blocked` with `blocked_on` saying what; `season plan` refuses them.

### Calendar

Levels slide; four do not: **L37 (Oct 31), L63 (Nov 26), L92 (Dec 25),
L98 (Dec 31)**. A world's WP7 must pass stage QA three days before its
first level so clips can be scheduled with `publishAt`. Until World 1's
levels exist as clips, the channel keeps publishing from the current pipeline.

## 7. Open questions (operator decides; code does not)

- **Sleep compilations.** Looping levels to 60–180 minutes is the pattern the
  reused/repetitive-content policy is most likely to catch. Not built until
  decided.
- **YPP threshold.** The handoff says 1,000 subscribers + 8,000 hours; the
  criteria this repo last saw are 1,000 + 4,000 public watch hours in 12
  months. Check YouTube's own page before using either as a target.
- **Persona replies** within two hours, cross-posting and fan votes are
  operator work; nothing here posts.

## 8. Test on the build machine, step by step

Each step says what to run and what to look at. Stop at a step that fails.
Commands assume the repo root and `.venv/bin` on the PATH.

**0. Move in.** On the old machine, with the server stopped, copy what git
does not carry: `data/` (the database and renders), `.env`, and each
`channels/<id>/rules.md` and `channels/<id>/token.json`. On the new one:

    git clone git@github.com:bondzai/shorts-factory.git && cd shorts-factory
    git checkout series-layer
    python3 -m venv .venv && .venv/bin/pip install -e ".[youtube]"
    # copy data/, .env, channels/*/rules.md, channels/*/token.json into place
    brew install ollama && brew services start ollama   # or the Linux installer
    ollama pull qwen2.5vl:3b && ollama pull qwen2.5:3b
    factory doctor && factory brains --test ollama && pytest -q

`doctor` clean, the brains answer, every test passes.

1. **Trace (WP1).** `pytest -q tests/test_trace.py` — the same seed writes a
   byte-identical `trace.npz`, and redrawn frames equal the shipped ones.
   `factory render-check --stage zigzag --seed 7 --cast main` renders one race
   with the cast; open the `trace.json` beside it.
2. **Cast (WP2).** `factory stage-qa --stages zigzag,funnels,plinko --seeds 48 --cast main`
   — every regular entrant wins 10–45%. Render five with `render-check --cast main`
   and watch: Blaze fast and loose, Tide steady, Volt wobbly, Moss average.
3. **Season file (WP3).** `factory season check` — 0 errors; the blocked
   levels are listed with what each waits for. Read L01–L20 in
   `channels/main/season/s0.yaml` against docs/09.
4. **Plan and render (WP4).** `factory season plan --levels L01..L03`, then
   `factory work`. `factory season status` shows each level's clip, story
   attempts and copy source. A level that fails `story_unsatisfiable` gets its
   story rewritten, never a higher cap.
5. **Standings (WP5).** Approve two level clips on Today (or `factory approve`).
   `factory season standings` must equal `factory season standings --recompute`.
   Reject one and restore it: still equal.
6. **Copy (WP6).** `factory copy --clip <id>` on three clips prints the plan
   hint, the chosen text and the fallback side by side. `season status` shows
   how many fell back; above ~30%, try another local model before touching
   the rules.
7. **Long-form (WP8).** `factory longform --levels L01..L03 --kind tournament`
   writes a 16:9 video, `chapters.txt` and `description.txt` under
   `data/out/main/longform/`. Watch the first minutes: a card per level, the
   race in the middle, the table either side.

Measured on the development machine (2026-09-25): two levels planned,
rendered with story checks, copied (template fallback, no brain) and
approved end to end in 10 s of work; the tournament long-form of those two
rendered at 8.5x realtime.

## 9. What changed from the handoff

| Handoff said | Now | Why |
|---|---|---|
| "Rewrite" was never the plan; the request was | Extend (2.1) | The handoff's own rule, and the pipeline works |
| `story.must` may require a winner or an elimination (`eliminated_includes: blaze`) | Events and mechanism only by default (2.4) | Seed-searching a result is rigging; the channel sells a fair race |
| Title keyword required in the first 3 words | Preferred, not required | Shorts views come from the feed, not search |
| Titles may name one persona ("Can Blaze hold the lead?") | Name all entrants or none | A title naming one marble only passes when it lost |
| Last frame matches first for a seamless loop | Dropped | A falling race cannot loop; `docs/03` |
| Sleep compilations built by looping levels | Not built yet (§7) | Policy risk |
| YPP 1,000 subs + 8,000 hours | Verify first (§7) | Not the criteria on record here |
| `channels/gravity-lab/` | `channels/main/` | The channel's id in the database; a rename is a separate migration |
| trace positions float32, angles stored | float64, no angles | Exact redraw; nothing draws rotation |
| L13 "Blaze has fallen into every trapdoor" as a `must` chain | Rewritten from results | Rule 2.4 |
