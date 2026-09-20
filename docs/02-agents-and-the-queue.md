# Agents and the queue

The factory does not care which model does the thinking. It separates two
things that are usually tangled: **judgement** (which the brain supplies) and
**arithmetic** (which the server keeps). A brain proposes a title; the server
measured the clip. A brain says "looks fine"; the server already knows the
similarity score. No brain can change a measurement.

## Two ways to run a brain

**External, over MCP.** Codex, Claude Code and Gemini CLI can all connect to
the factory as an MCP server. Register it once — Settings → Brains shows the
exact command for each — then paste the standing prompt from the Queue screen.
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
course, or `plan-week`, `review`, `retitle`. An agent claims the oldest task
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
