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

## Letting an agent drive it

```bash
factory mcp                  # read and build only
factory mcp --allow-publish  # also approve and publish
```

An MCP server on stdio, so Claude Desktop, Claude Code or Codex can run the
pipeline. Point a client at it:

```json
{
  "mcpServers": {
    "shorts-factory": {
      "command": "/path/to/shorts-factory/.venv/bin/factory",
      "args": ["mcp"]
    }
  }
}
```

### Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.shorts-factory]
command = "/path/to/shorts-factory/.venv/bin/factory"
args = ["mcp"]
startup_timeout_sec = 120

[mcp_servers.shorts-factory.tools.approve_clip]
approval_mode = "approve"

[mcp_servers.shorts-factory.tools.publish_approved]
approval_mode = "approve"
```

The two `approval_mode = "approve"` blocks are a second gate on top of
`--allow-publish`: even with publishing enabled on the server, Codex has to ask
you before it fires. Keep both.

Codex spawns the server itself, so the server sees Codex's environment, not your
shell's. Put `ANTHROPIC_API_KEY=...` in the repository's `.env` — the factory
reads it relative to its own location, so it works whatever directory the agent
runs from. Without it the first tool call fails with an explanation naming the
file; it does not fail silently and nothing is spent.

Tools: `list_channels`, `list_modules`, `plan_clips`, `build_clips`,
`review_queue`, `get_clip`, `reject_clip`, `approve_clip`, `publish_approved`,
`get_analytics`, `set_metrics`, `read_rules`, `append_rule`, `recent_logs`.

**Approving and publishing are refused unless you pass `--allow-publish`.** The
design rests on a human watching the first second before a clip goes out, and an
agent that can approve its own work removes exactly that. Everything up to the
review queue is always available, because planning and rendering are reversible
and cost cents. Rejecting is always available too — throwing work away is safe.

The refusal is a `ToolError`, not a bare exception, because the SDK suppresses
the message of anything it did not expect: the agent needs to read *why* it was
refused, not just that it was.

Every tool call is written to the event log with `actor: "mcp"`, so
`factory logs --event mcp.` answers what the agent did without asking it.

## Disk, and clips that stopped halfway

```bash
factory gc --dry-run      # say what would go
factory gc
factory resume --dry-run  # list clips stuck between stages
factory resume
```

Every clip leaves `video.mp4` (silent, pre-mux), `audio.wav` and `clip.mp4`
behind — about 4.5 MB, of which roughly 3 MB is dead the moment the mux lands.
The pre-mux pair is dropped automatically after each build; `gc` also sweeps
directories left by earlier runs and by `render-check`, which never goes through
the pipeline.

`clip.mp4` itself is only removed once a clip's outcome is settled *and* it is
old enough: `[retention] rejected_days = 3`, `published_days = 30`, `-1` to keep
forever. A clip waiting in the review queue is never touched whatever its age,
and a swept clip is marked `purged_at` so it is never counted twice. `data/out`
is left alone entirely — the copy in the publish queue is what you actually
shipped.

**Resume** exists because a build that dies after the render but before QC used
to strand the clip: re-running it paid to re-render and re-title work already on
disk. Each stage is now skipped when its output is present and still valid, so
resuming a stranded clip costs one QC call instead of a full rebuild — measured
at 0.6s against roughly 6s. `--include-failed` picks up clips that errored;
`build --force` ignores all of it and redoes everything.

## Choosing a model per agent

The four agents are not the same job, so they do not have to share a model.
`[llm.agents]` in `config.toml` sets one each, `[llm.pricing]` keeps the cost
figure true when they differ, and the log records which model spent what:

```bash
factory cost --days 7
```

```
agent      model                 calls        in      out    $/call     total
analyst    claude-opus-5             3     27000     2400   0.05100    0.1530
qc         claude-haiku-4-5         41     94300     1230   0.00104    0.0427
```

Change one agent at a time and watch two numbers together: the cost here, and
how often you overrule QC by hand in the review queue. A cheaper QC that starts
letting weak hooks through does not show up as an error — it shows up as you
rejecting more clips yourself. A model missing from `[llm.pricing]` is billed at
the default rate and marked `~`, rather than quietly costed wrong.

## Logs

```bash
factory logs --limit 40
factory logs --level error
factory logs --event clip.        # or agent. / mcp.
factory logs --clip dcea65130017
```

One JSON object per line under `data/logs/factory-<date>.jsonl`, and a Logs
screen in the web UI with the same filters. The runs table says a build happened
and what it cost; this says what happened inside it — which clip reached which
stage, what each agent call cost in tokens and dollars, and the exact reason a
clip was thrown out.

Logging never raises. A broken log must not stop a build, and a half-written
final line from a killed process is skipped rather than losing the file.

## Channels

A channel owns its clips, its rules, its publish driver, its credentials and its
sameness history. Nothing crosses between them, and that is the point: what a
marble audience rewards says nothing about a crypto one, so one shared rules file
would actively mislead both.

```bash
factory channels list
factory channels add "HODL Tales" --handle @HODLTales --variant sysviz/hash_avalanche
factory channels edit hodl --pause
```

Every command works on one channel. With a single active channel it is chosen for
you; with several, pass `--channel <id>`. Pausing a channel takes it out of that
choice without deleting anything.

| What | Where |
|---|---|
| Rules | `channels/<id>/rules.md` |
| OAuth token | `channels/<id>/token.json` |
| Manual publish queue | `data/out/<id>/publish-queue/` |
| Clips, runs, digests | one `channel_id` column each |

`--variant generator/variant` restricts what the Idea agent may propose for that
channel; leave it empty and the channel takes any ready module. The id is
internal and never changes — rename the display name whenever you like.

An existing single-channel database migrates itself on the next connect: the
column is added, a channel called `main` is created, and every clip is adopted
into it. Nothing is lost and the migration is a no-op the second time.

## The review UI

```bash
factory serve
```

Opens on http://127.0.0.1:8765. One clip at a time, playing, with its QC verdict
and technical numbers beside it; <kbd>A</kbd> approves, <kbd>R</kbd> rejects,
<kbd>J</kbd>/<kbd>K</kbd> move, <kbd>space</kbd> pauses. Plan, Build, Publish and
Digest are buttons that stream their log into the page.

The channel picker in the header switches everything on the page, and shows how
many clips are waiting on each. One job runs at a time across all channels — a
build on one channel blocks a build on another, and the page says which.

Five screens, split by how often you touch them:

| Screen | For |
|---|---|
| Review | the fifteen minutes that matter: watch, approve, reject |
| Library | every clip, filterable by status and module, with search — where you go when something went wrong |
| Analytics | views per clip in publish order, retention by variant and by QC hook score, distance to the monetisation gates |
| Rules | edit this channel's rules.md in place, and accept Analyst proposals one at a time |
| Runs | job history with cost, so a failure at 08:40 is still visible at noon |

The Library's filter chips are built from what the server reports, not from a
list in the page. Finish `market_replay`, set `ready = True`, and it appears as a
filter, a planning option and an Analytics row without the UI knowing its name.

Two places where the UI states its own limits rather than looking clever:
Analytics prints n on every group, and the hook-score panel says outright that
the buckets below the QC floor are empty by construction — the grader never sees
its own failures.

This exists because the approval step is the one part of the day you cannot do
from a table of text — a hook is either there in the first second or it is not,
and you have to watch it to know. Everything else works fine from the CLI.

It binds to localhost and has no authentication by design: it reads your
database and spends your API credit, so it should not be reachable from
anywhere else.

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
