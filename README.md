# shorts-factory

A content pipeline for vertical short video where the clips are produced entirely
in code, so the only human time is deciding and approving. Built around one idea:
**the generator is a pluggable module, the pipe is written once.**

```
Generator slot            Shared pipe
  physics      ──┐        render → metadata (EN) → QC → [your approval] → publish → metrics
  market_replay ─┼──────▶                                                            │
  sysviz       ──┘        rules.md ◀────────────── Analyst ◀───────────────────────────┘
```

Your day, 30 minutes:

| | Command | Time |
|---|---|---|
| 1 | `factory plan --count 3` — read what it proposes, drop what you dislike | 5 min |
| 2 | `factory build` — renders, titles and QCs while you do something else | 0 min |
| 3 | `factory queue` then `factory approve <id>` | 15 min |
| 4 | `factory publish` | 0 min |
| 5 | `factory digest` — weekly is enough at first | 10 min |

## Install

```bash
brew install ffmpeg
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
factory doctor
factory init
```

Credentials: `ant auth login`, or export `ANTHROPIC_API_KEY`. Nothing is
hardcoded and no `.env` is required. Being logged into Claude Code does **not**
give this project credentials — it is a separate process with its own auth.
`factory doctor` checks what the SDK actually resolved, not just that a client
object could be constructed.

To render a clip without spending anything on the API, and without touching the
database:

```bash
factory render-check --variant marble_race --seed 42
```

## What is actually built

| Piece | State |
|---|---|
| `factory/generators/physics.py` | Real. Two variants, pymunk simulation, PIL frames, synthesised impact audio, deterministic from the seed. |
| `factory/generators/market_replay.py` | Stub. Docstring lists the four steps; nothing else in the pipeline changes when you finish it. |
| `factory/generators/sysviz.py` | Stub, same. |
| `factory/agents/` | Real. Four agents: Idea, Metadata, QC, Analyst. |
| `factory/publish/manual.py` | Real, and the default. Writes `data/out/publish-queue/` for you to upload by hand. |
| `factory/publish/youtube.py` | Real API calls, untested against a live account. Uploads land **private**. |

## The three decisions that matter

**QC can reject on its own.** `factory/agents/qc.py` has two layers: arithmetic on
ffprobe output plus the perceptual hash, and a vision pass over four frames. Either
rejects. This is what lets the queue grow — you approve by exception instead of
inspecting every clip, so 3 clips a day and 10 clips a day cost you the same 15
minutes. Thresholds are in `config.toml` under `[qc]`.

**Sameness is a hard reject.** Every clip is hashed at four points and compared with
every clip in the database. A channel that publishes 300 reseeds of one template is
the shape YouTube's inauthentic-content policy describes, so `max_sameness` is
enforced in code, not left to the model's judgement.

**The Analyst cannot propose rules until n is large enough.**
`[analyst] min_published_for_rules` defaults to 30 published clips with metrics.
Below it, proposed rules are discarded in `factory/agents/analyst.py` even when the
model sounds confident — with n that small you would be tuning the pipeline against
noise. The digest still prints the numbers.

`rules.md` is the memory shared between runs: the Idea and Metadata agents read it
every time, the Analyst appends to it between the `analyst:begin` / `analyst:end`
markers. Edit it by hand whenever you want; that is the intended way to steer.

## Metrics without the API

While `[publish] driver = "manual"` there is nothing to read automatically. Copy the
numbers out of YouTube Studio:

```bash
factory set-metrics <id> --views 4120 --avg-view-pct 71.4 --swipe-away-pct 23.0
```

Switch to `driver = "youtube"` in week 3 and `factory pull-metrics` does it. Note
that YouTube has no swipe-away metric: the driver derives it from
`audienceWatchRatio` in the first 2% of the clip. Useful, not official.

## What the physics numbers are, and why

The constants at the top of `generators/physics.py` are not taste, they were
measured. Two of them decide whether a clip exists at all:

- **Ramp slope.** At a slope of 0.15 the marbles stop dead four seconds in — they
  roll to a ramp's rounded end cap, perch on it, and the rest stack up behind.
  Each ramp now drops its full share of the height, giving a slope near 0.4.
- **Funnel throat.** Below about five ball radii the balls arch across the
  opening and the pour never starts: at 3.4 radii, 54 of 54 balls were still
  sitting above the throat when the clip ended. Six radii drains every seed
  tested.

Clip length is set with gravity rather than geometry, because gravity is a dial
that cannot jam. Measured over 60 seeds of `marble_race`: every seed produces a
finished race, 50 on the first attempt and 10 on the second, 12.4s to 19.4s with
a median of 16.1s, and all four colours win a fair share. `funnel_drop` runs
about 12-13s and drains completely.

About one race course in six still wedges a marble. That is caught by a stall
check and retried on a seed derived from the original, so the run stays
reproducible from `seed` alone.

**Loudness.** The first clip ever rendered measured -26 LUFS integrated while
peaking near full scale: all crest factor, no energy between the hits. Things
that did not fix it, in order of how much time they wasted: single-pass
loudnorm (+4 dB), two-pass loudnorm (+0.1 dB more — linear gain that large would
clip, so it refuses), and detecting more impacts (none; the extra hits were weak
ones).

What fixed it was the length of a single hit. `IMPACT_DECAY` was 34/s, which
rings for about 30 ms, and the transient buffer then truncated even that. At
18/s — with the buffer sized from the decay rather than fixed — every clip lands
at -14.1 to -14.6 LUFS, roughly 3 dB inside the `[qc]` window on both variants.
The tapped-delay tail and the soft limiter still earn their place, but they were
treating a symptom.

The four constants at the top of `audio.py` were swept together against ebur128
(24 combinations, three clips) rather than set by ear. Anything at decay 18 or
below now saturates at the loudness target, so the remaining knobs buy at most
0.5 dB — not worth the extra compression. If you change the synthesis,
re-measure: `factory render-check` prints the value QC will see.

## Cost

Four Claude calls per clip at most (one Idea call covers a whole batch), each stored
per clip in the `cost_usd` column — `factory status` totals it. At three clips a day
this is cents, and the number is there so you can see it rather than guess.

## Adding a generator

1. Copy `market_replay.py`, implement `generate()` returning a `GeneratedClip`.
2. `register(YourGenerator())` at the bottom, import it in `generators/__init__.py`.
3. Set `ready = True` when it produces a clip you would publish.

Nothing downstream changes. That is the whole point of the layout.

## Not done, and what is unverified

- **No agent has ever been called against the live API.** The prompts and
  schemas are written and validate locally, but `factory plan` will be their
  first real run — expect to fix something there. Everything from the generator
  through QC's arithmetic layer has been run end to end.
- No scheduler. Run the commands yourself for the first few weeks; wire `cron`
  once you trust the queue.
- Facebook Reels publishing needs a Page, the Graph API and app review. Not
  written — export from `publish-queue/` and upload manually.
- `youtube.py` has never run against a real account.
