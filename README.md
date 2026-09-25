# shorts-factory

A content pipeline for vertical short video where the clips are produced entirely
in code, so the only human time is deciding and approving. Built around one idea:
**the generator is a pluggable module, the pipe is written once.**

```
Generator slot            Shared pipe
  physics      ──┐        render → metadata (EN) → QC → [your approval] → publish → metrics
  battle       ──┘──────▶                                                            │
                          rules.md ◀────────────── Analyst ◀───────────────────────────┘
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

### Two ways to run it, and one of them needs no key

**The agent is the brain** — `render_clip`, `submit_metadata`, `submit_qc`.
Nothing here calls a model, so no Anthropic credential is needed at all. The
calling agent already is one: it picks the variant, reads the rules, looks at
the four frames `render_clip` hands back, writes the title and scores the hook.
Rendering is pure simulation, so the machine does the part a model would only
be guessing at.

**This project's agents are the brain** — `plan_clips`, `build_clips`. Idea,
Metadata and QC run in-process and need `ANTHROPIC_API_KEY`. Use this from cron,
where no agent is watching.

The split that makes the first one safe: **the caller supplies judgment, the
server keeps the arithmetic.** Aspect ratio, duration, loudness and similarity
to earlier clips are measured here from the actual file on every call and
combined with the caller's verdict by the same `qc.decide` the in-house agent
faces. An agent claiming `verdict: pass, hook_strength: 5, looks_templated:
false` on a clip measuring 0.914 similarity is still rejected, because it is
never asked about similarity — that is checked, not believed.

Tools: `list_channels`, `list_modules`, `render_clip`, `submit_metadata`,
`submit_qc`, `plan_clips`, `build_clips`, `review_queue`, `get_clip`,
`reject_clip`, `approve_clip`, `publish_approved`, `get_analytics`,
`set_metrics`, `read_rules`, `append_rule`, `recent_logs`.

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

## Publishing to YouTube

```bash
pip install -e '.[youtube]'
factory youtube connect --channel main   # a browser, once, per channel
factory youtube status
```

Then set the channel's driver to `youtube` and press **Upload to YouTube**
on Team. A clip goes up private with a `publishAt` for the next slot, its
question is posted as a comment, and a retitle of a published clip is
pushed to the video. Nothing uploads by itself, and agents cannot upload at
all. See docs/07.

## Being told when a run finishes

```toml
[notify]
webhook_url = "https://hooks.slack.com/services/..."
on = ["run.finished", "run.failed"]
```

```bash
factory notify   # post a test and report what each endpoint said
```

Two sinks, both set in `.env`: `FACTORY_WEBHOOK_URL` (Discord, Slack, ntfy)
and a Telegram bot (`FACTORY_TELEGRAM_TOKEN` + `FACTORY_TELEGRAM_CHAT_ID`).
Telegram is the one that talks back: a clip that passes QC arrives as the
video with Approve and Reject under it, and the bot answers `/status`,
`/queue`, `/clip`, `/approve`, `/reject` and `/daily` while `factory serve`
runs. See docs/02 for the three-step setup.

Pointed away from this machine on purpose. The CLI, the web UI and the MCP
server all write the same SQLite file, so none of them needs telling what the
others did — they can already see it. The thing that cannot see it is you,
asleep, while an agent builds clips at three in the morning.

The hook lives in `db.finish_run`, which every surface already calls, so a run
started from Codex, from cron and from the browser all notify identically. The
payload carries a plain `text` line — which is what Slack, Discord and ntfy each
read — plus the structured fields under it.

Delivery runs off the calling thread so a slow endpoint cannot stall a build,
and is joined at exit: a daemon thread dies with the process, and `factory
build` finishes its last run and exits immediately, so without that join every
notification a CLI command sent was silently lost.

The open web page polls every five seconds whether or not it started anything,
so a build an agent ran while the tab sat there still shows up. It only
re-renders when something actually differs — rebuilding the review pane would
restart the clip that is playing.

## How many clips a variant can hold

`sameness` is the highest similarity against every earlier clip on the channel,
so it can only climb as the library grows. Generating 25 `marble_race` clips in
a row and applying the guard each time, 17 were accepted and 8 rejected, with
rejections clustering towards the end: the first five all passed, the last few
mostly did not. A variant has a capacity, and that is arithmetic rather than
taste.

Adding a variant adds capacity; tuning one variant's looks moves its ceiling
but does not remove it. This is the reason a 100-clip target needs more than
one variant — and the reason stages and the season's cast now vary what a
viewer sees, not only who wins.

## Playbooks: the prompts, in git

```bash
factory playbook                          # list them
factory playbook make-clip --channel main # print one, ready to paste
```

A playbook is markdown under `prompts/` with `{placeholders}` filled from the
live database — the channel's rules, what it has made recently, how those clips
performed, the current hard gates. That substitution is the point: a prompt
pasted from a previous session is stale the moment a clip publishes, and a stale
prompt is how an agent proposes what was already made last week.

There is an MCP tool of the same name, so a connected agent fetches its own
instructions instead of being handed them.

The retention advice inside `make-clip.md` prints the numbers it rests on
directly above itself, so when the numbers move the advice can be argued with
rather than followed out of habit.

## The caption, the title, and the gauge on the title

YouTube's own analysis of the first published race said the same thing twice:
76% average viewed, 25% stayed. The clip holds whoever starts it and loses
whoever is deciding whether to. Two things decide that — the caption in the
first second and the title — and until this section neither could be changed.

**The caption is measured, not written.** `physics` now records every marble's
crossing, not only the winner's, and when the runner-up is inside a second the
opening caption is the margin: `DECIDED BY 0.4s`. That is a fact the simulation
produced, on screen in the one second the viewer gives us. A runaway race falls
back to the config line. `facts.margin_s`, `facts.finishes` and
`facts.hook_text` say which happened.

```bash
factory rehook <clip> "DECIDED BY 0.4s"   # re-burn a caption; same seed, same race
factory rehook <clip> --measured          # let the render choose from what it measures
```

Only pixels change, so the clip stays where it was in the pipeline — a queued
clip stays queued, an approved one goes back to the queue. A published clip
refuses: the caption is in the uploaded file.

**The title can change, and the change keeps its receipt.**

```bash
factory retitle <clip> "This marble race is decided by 0.4 seconds" --why "stake first"
```

`retitle` keeps the old title and the metrics at the moment of the change
(views, average viewed, swiped away, when they were pulled). Without that a
retitle is a lever with no gauge: next week's numbers would be credited to a
title that was only on the video for half the week. On a manual-driver channel
the tool says the new title also has to be typed into Studio.

**The comment prompt** is a third field on metadata: a question to pin as the
first comment. Only one the clip answers — which colour the viewer backed — and
the Review screen's "Copy for upload" puts it under the hashtags.

The Review screen edits all three in place; the MCP `submit_metadata` takes
`hook_text` and `comment_prompt`, and `retitle` is its own tool. The `retitle`
playbook lists published clips worst-swipe-away first with their caption and
their title history, so an agent proposes from the numbers rather than from
taste.

One honesty note that this work surfaced: the first published title, "decided
by half a second", was written before the margin was recorded anywhere — the
clip's stored description at the time was the seed number. It cannot be
checked now. Every race rendered from here on records its margin, and the
title playbook says to use it.

## The console

Four screens. **Team** is home: a one-paragraph briefing, then **Your
decisions** (review with `A`/`R`/`J`/`K`, run QC, publish, plan the next
season levels), then **the office** — a desk per agent and built-in brain
saying what it is doing and did today, with start/stop for workers — and,
collapsed below, jobs and spend and the activity log. **Season** (levels,
what each waits for, the table), **Clips** (every piece of work from queued
to published, and the bin) and **Settings** (the channel, its rules, the
brains, the docs). A command bar in the header (⌘K) runs it all by name —
`plan L02..L04`, `make 3 zigzag`, `import`, `run qc`, `open L05` — showing
what each write will do before Enter runs it.

Every screen follows one contract — title row, toolbar (search · filter
chips · sort · count), content, pagination — and every list answers one
shape from the server: `{items, total, page, page_size}` with a whitelisted
`sort`/`dir`, `page_size` of 25/50/100, and the filters kept in the URL
(`#/clips?status=published&sort=views&dir=desc&page=2`), so refresh, back
and a shared link land on the same view. The pieces are in `web/src/ui`;
a screen that needs a ninth is a screen that is doing too much.

Vite + React + TypeScript, source under `web/`. The build is committed to
`factory/static/dist` so `factory serve` needs no node; after changing the
source:

```bash
cd web && npm install && npm run build   # typechecks, then builds into the package
npm run dev                              # live reload on :5173, API proxied to :8765
```

## Brains: any model, one database

Two ways to run an agent, and the factory does not care which:

* **External, over MCP.** Codex, Claude Code, Gemini CLI — anything that
  speaks MCP registers the server once (Settings shows the exact command for
  each) and reads the playbooks. No key goes into this project. This is how
  every clip so far was made.
* **Built-in.** The factory calls a model itself for Plan, Build and Digest.
  Which model, and whose, is configuration: a provider plus a model per agent,
  set on the Settings screen or in `config.toml`.

Providers come in two kinds. `anthropic` uses the Anthropic SDK. `openai`
is anything that speaks the OpenAI chat API — OpenAI, Ollama and LM Studio on
this machine, Groq, Gemini's compatible endpoint, OpenRouter — with structured
output done the portable way: "reply with JSON matching this schema",
validated with pydantic, retried once with the validation error. A local
model costs nothing and the ledger says so.

```bash
factory brains                        # where each agent runs, and whether it can
factory brains --test ollama --model qwen2.5vl:7b
factory config list                   # every knob the page can turn
factory config set qc.max_sameness 0.9
```

Keys never pass through the page: a provider carries the *name* of the
variable in `.env`, and the page says whether it is set. QC judges four
frames, so it refuses a provider marked as unable to see images — that is a
rule, not a hint.

`config.toml` stays the default. Anything changed on the page is an override
in the `settings` table, shown as one, resettable. The database's own
location is the one thing that cannot come from the database.

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
factory channels add "Second Channel" --handle @second --variant physics/marble_race
factory channels edit second-channel --pause
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
list in the page. Register a new generator, set `ready = True`, and it appears as
a filter, a planning option and an Analytics row without the UI knowing its name.

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
| `factory/generators/battle.py` | Real. A ball arena: last one standing, deterministic from the seed. |
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

About one race stage in six still wedges a marble. That is caught by a stall
check and retried on a seed derived from the original, so the run stays
reproducible from `seed` alone.

**Variety.** Two independent judges called the original race template-like:
the perceptual hash put consecutive clips at 0.875 and 0.914 against a 0.88
reject line, and an agent shown four frames set `looks_templated` without seeing
those numbers. Both were right — every seed differed only in ramp slope and
finishing order, and neither shows in a still frame.

What varies now is what a viewer can see before anything moves: the backdrop
(six palettes), ramp count, which side the stage starts from, ramp thickness,
marble count and marble size. Slope is held near 0.4 throughout, because that is
the number that decides whether the marbles move at all.

Ramp count and span move together on purpose: span is derived from the slope
rather than chosen, so more ramps means shorter ones and the total path length —
and the clip's duration — stays where QC wants it. Marble count is capped by how
long the first ramp is, since a nine-ramp stage would otherwise start five
marbles stacked on each other.

Measured over 40 seeds after the change: every seed produces a finished race,
33 on the first attempt, durations 10.2s to 18.9s with none under the QC floor,
and across 28 pairs of clips the highest similarity is 0.867 — no pair now
reaches the reject line. Five-ramp stages were dropped from the options after a
forced test stalled 12 times out of 12.

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

1. Copy `battle.py`, implement `generate()` returning a `GeneratedClip`.
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
