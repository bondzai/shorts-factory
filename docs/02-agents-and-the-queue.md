# Agents and the queue

The factory does not care which model does the thinking. It separates two
things that are usually tangled: **judgement** (which the brain supplies) and
**arithmetic** (which the server keeps). A brain proposes a title; the server
measured the clip. A brain says "looks fine"; the server already knows the
similarity score. No brain can change a measurement.

## Two ways to run a brain

**External, over MCP.** Codex, Claude Code and Gemini CLI can all connect to
the factory as an MCP server. Register it once — Settings → Brains shows the
exact command for each — then hand it the standing prompt.

Two ways to hand it over, the same prompt either way:

    bin/cowork          # renders the prompt and starts Claude Code on it
    AGENT=codex bin/cowork
    bin/cowork --print  # just the text, to paste anywhere

or **Clips → Hand off to an agent → Copy**, then paste into an agent you
already have open. The prompt is rendered fresh from the database each time —
this channel's rules, its recent clips, the hooks skill, your Directions — so
an agent started today never works from last week's brief.
The prompt is six lines and never changes, because each task carries its own
full instructions. No API key goes into this project.

**Built-in.** The factory calls a model itself for Plan, Build, Digest and
`factory work`. Which model is configuration: Settings → Brains lists
providers (Anthropic, OpenAI, Ollama on this machine, Groq, Gemini,
OpenRouter, or any OpenAI-compatible endpoint) and which one each of the four
agents uses. **Test** makes a one-word round trip so you know it works before
an agent finds out the hard way. QC judges four frames, so it refuses a
provider that cannot see images.

## The queue

A task is a kind plus parameters — `make-clip` with a variant and maybe a
stage, or `plan-week`, `review`, `retitle`. An agent claims the oldest task
(highest priority first), gets that kind's playbook with the task's parameters
on top, does it, and reports done or not-doable with a reason. A claim expires
after 45 minutes so a vanished agent does not hold work forever.

The step strip under each task — claimed, rendered, described, QC, finished —
is read from the event log, not written by anyone, so it cannot disagree with
what happened.

## Playbooks

The instructions an agent gets live in `prompts/*.md`, in git. They contain
`{placeholders}` filled from the database at the moment of use: the channel's
rules, what it made recently, how those clips performed, the current gates. A
prompt pasted from last week would already be wrong; one rendered now is not.

## Starting an agent from the console

**Team → Workers** runs the agent for you, so a queue never waits for a
terminal. Pick `claude` or `codex` for a channel and press **Start now**: the
server renders the work playbook fresh from the database and runs the agent
non-interactively with only the factory's MCP tools pre-approved — exactly
what `bin/cowork --unattended` does, without the terminal. Its output is a
log you can open on the same row. **Auto** keeps a worker on the channel:
whenever tasks are queued and no agent is running, the server starts one,
and the flag survives a server restart.

The agent binary must be on the PATH of the machine running `factory
serve`. Inside the Docker image it is not, and the page says so; there,
`bin/cowork` on the host or an outside agent is the way.

**Connect an outside agent** on the same screen has the config to copy for
Claude Code (one command), Codex (`~/.codex/config.toml`), any MCP client
(JSON), the prompt command, and the terminal one-liner. An agent connected
this way appears on the Team screen by the name it gives `next_task`.

## Watching the team

The **Team** screen is the whole factory from the manager's chair, across
every channel: each agent by the name it gave `next_task`, whether it is
working, ready, idle or away, the task it holds and which step it is on,
what it finished today (tasks, clips, QC passes, cost), and a feed of the
log read out loud. Your own card is the deciding — how many clips wait for
you, and what you settled today. Nothing is recorded for this screen; it is
the tasks table and the event log, so it cannot disagree with them.

## Telegram: the factory in your pocket

Three steps and one message:

1. Make a bot with [@BotFather](https://t.me/BotFather) and copy its token
   into `.env` as `FACTORY_TELEGRAM_TOKEN`.
2. Restart the server and send the bot `/start`. It replies with the chat
   id. Until it has one it answers nothing else, so a stranger who finds the
   bot cannot touch your clips.
3. Put that id in `.env` as `FACTORY_TELEGRAM_CHAT_ID` and restart again.

From then on every notification that goes to the webhook goes to the phone
too, and a clip that passes QC arrives as the video with **Approve** and
**Reject** under it — the same call as A or R on Today. The bot answers:

| command | what it does |
|---|---|
| `/status` | every channel: to decide, to upload, queued, who is working |
| `/queue` | the clips waiting for your decision, with their short ids |
| `/clip <id>` | sends that clip to watch, with the two buttons |
| `/approve <id>` | approve; the id is the first few characters, the queue shows them |
| `/reject <id> [why]` | reject; the reason is what the next planner reads |
| `/daily` | the upload reminder, now |

Only the paired chat is answered. The bot long-polls Telegram from inside
`factory serve`, so nothing on this machine is exposed and it works from a
container as well as a laptop. `factory notify` posts a test to every sink
that is configured; Settings → Alerts shows the same and has a button.
