# Start here

A small factory that makes short vertical clips from code — marble races, a
ball arena, coin ASMR — and helps you decide which ones to publish. Agents
do the making and judging; you do the deciding, about thirty minutes a day.

## How it fits together

Four lanes. You never talk to an agent directly: you add work, the server
holds it, whichever agent is around does it, and the result comes back to
you as a clip to approve.

<svg viewBox="0 0 760 470" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, sans-serif" font-size="12">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--dim)"/></marker>
    <marker id="arrow-key" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--key)"/></marker>
    <style>
      .lane{fill:var(--panel);stroke:var(--line);rx:10}
      .lane-name{fill:var(--faint);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase}
      .card{fill:var(--bg);stroke:var(--line);stroke-width:1;rx:8}
      .card.key{stroke:var(--key)}
      .t{fill:var(--ink);font-weight:600}
      .s{fill:var(--dim);font-size:10.5px}
      .route{fill:none;stroke:var(--dim);stroke-width:1.3;marker-end:url(#arrow)}
      .route.key{stroke:var(--key);marker-end:url(#arrow-key)}
      .label{fill:var(--dim);font-size:10px}
    </style>
  </defs>

  <rect class="lane" x="8" y="8" width="744" height="92"/>
  <text class="lane-name" x="20" y="26">You</text>
  <rect class="card key" x="24" y="38" width="166" height="48"/><text class="t" x="36" y="58">Console</text><text class="s" x="36" y="74">Team · Season · Clips</text>
  <rect class="card" x="206" y="38" width="166" height="48"/><text class="t" x="218" y="58">Telegram</text><text class="s" x="218" y="74">clip + Approve / Reject</text>
  <rect class="card" x="388" y="38" width="166" height="48"/><text class="t" x="400" y="58">Discord / Slack</text><text class="s" x="400" y="74">done · daily reminder</text>
  <rect class="card" x="570" y="38" width="166" height="48"/><text class="t" x="582" y="58">YouTube</text><text class="s" x="582" y="74">uploads on your press</text>

  <rect class="lane" x="8" y="126" width="744" height="92"/>
  <text class="lane-name" x="20" y="144">Server</text>
  <rect class="card key" x="24" y="156" width="166" height="48"/><text class="t" x="36" y="176">Web API</text><text class="s" x="36" y="192">factory serve, one password</text>
  <rect class="card" x="206" y="156" width="166" height="48"/><text class="t" x="218" y="176">Task queue</text><text class="s" x="218" y="192">what was asked for</text>
  <rect class="card key" x="388" y="156" width="166" height="48"/><text class="t" x="400" y="176">Pipeline + gates</text><text class="s" x="400" y="192">render · measure · refuse</text>
  <rect class="card" x="570" y="156" width="166" height="48"/><text class="t" x="582" y="176">Notify</text><text class="s" x="582" y="192">webhook · Telegram</text>

  <rect class="lane" x="8" y="244" width="744" height="92"/>
  <text class="lane-name" x="20" y="262">Agents · MCP</text>
  <rect class="card key" x="24" y="274" width="166" height="48"/><text class="t" x="36" y="294">Claude Code / Codex</text><text class="s" x="36" y="310">you, or a Worker, starts it</text>
  <rect class="card" x="206" y="274" width="166" height="48"/><text class="t" x="218" y="294">factory mcp</text><text class="s" x="218" y="310">the tools agents call</text>
  <rect class="card" x="570" y="274" width="166" height="48"/><text class="t" x="582" y="294">Built-in agents</text><text class="s" x="582" y="310">QC · copy · idea — ollama</text>

  <rect class="lane" x="8" y="362" width="744" height="92"/>
  <text class="lane-name" x="20" y="380">Storage</text>
  <rect class="card key" x="24" y="392" width="166" height="48"/><text class="t" x="36" y="412">SQLite</text><text class="s" x="36" y="428">clips · tasks · standings</text>
  <rect class="card" x="206" y="392" width="166" height="48"/><text class="t" x="218" y="412">config · channels/</text><text class="s" x="218" y="428">cast · season · rules</text>
  <rect class="card" x="388" y="392" width="166" height="48"/><text class="t" x="400" y="412">Renders</text><text class="s" x="400" y="428">clip.mp4 + trace per clip</text>
  <rect class="card" x="570" y="392" width="166" height="48"/><text class="t" x="582" y="412">Event log</text><text class="s" x="582" y="428">data/logs — the feed</text>

  <!-- Every arrow runs in a gap between cards; none crosses a card. -->
  <path class="route key" d="M107,86 L107,156"/>
  <path class="route" d="M190,180 L206,180"/>
  <path class="route key" d="M190,298 L206,298"/>
  <path class="route" d="M289,274 L289,204"/><text class="label" x="296" y="235">next_task</text>
  <path class="route" d="M372,298 L451,298 L451,204"/><text class="label" x="382" y="290">render_clip</text>
  <path class="route" d="M495,204 L495,392"/><text class="label" x="502" y="350">clip + trace</text>
  <path class="route" d="M540,204 L596,274"/><text class="label" x="574" y="235">asks</text>
  <path class="route" d="M653,156 L653,113 L289,113 L289,86"/>
  <path class="route" d="M471,113 L471,86"/>
  <path class="route" d="M107,38 L107,28 L653,28 L653,38" stroke-dasharray="4 4"/><text class="label" x="300" y="23">only when you press it</text>
</svg>

Orange cards are the ones you will meet every day. Read it top to bottom:
you ask in the console, the server queues it, an agent picks it up
(`next_task`) and asks the pipeline to render (`render_clip`), the pipeline
writes the clip and its trace and asks the built-in brains for QC and copy,
and Notify tells you on Telegram or Discord. Everything is recorded in the
storage lane. The dotted line is the step that never happens on its own: a clip reaches YouTube only when you
press the button. On a manual channel that means you upload the file and
press **I uploaded it**; with the YouTube driver connected (docs/07) the
same press uploads it, private, scheduled for the slot.

## One clip, start to finish

Eight steps. The dot walks them in order; every step leaves a row or an
event behind, so Team and Telegram can tell you where a clip is
without asking the agent.

<svg viewBox="0 0 760 300" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, sans-serif" font-size="12">
  <defs>
    <marker id="arrow2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--dim)"/></marker>
    <style>
      .step{fill:var(--panel);stroke:var(--line);rx:8}
      .step.you{stroke:var(--key)}
      .n{fill:var(--key);font-weight:700;font-size:11px}
      .t{fill:var(--ink);font-weight:600}
      .s{fill:var(--dim);font-size:10.5px}
      .flow{fill:none;stroke:var(--dim);stroke-width:1.3;marker-end:url(#arrow2)}
    </style>
  </defs>
  <rect class="step you" x="10" y="20" width="170" height="56"/><text class="n" x="20" y="38">1</text><text class="t" x="34" y="38">You add work</text><text class="s" x="20" y="56">Clips → Add work, or Telegram</text><text class="s" x="20" y="68">→ a row in tasks (queued)</text>
  <rect class="step" x="200" y="20" width="170" height="56"/><text class="n" x="210" y="38">2</text><text class="t" x="224" y="38">An agent claims it</text><text class="s" x="210" y="56">Workers start it, or next_task</text><text class="s" x="210" y="68">→ claimed, by name</text>
  <rect class="step" x="390" y="20" width="170" height="56"/><text class="n" x="400" y="38">3</text><text class="t" x="414" y="38">Render</text><text class="s" x="400" y="56">a QA'd stage, pymunk, pygame,</text><text class="s" x="400" y="68">ffmpeg → clip.mp4 + facts</text>
  <rect class="step" x="580" y="20" width="170" height="56"/><text class="n" x="590" y="38">4</text><text class="t" x="604" y="38">Gates measure</text><text class="s" x="590" y="56">length · loudness · sameness</text><text class="s" x="590" y="68">too alike is refused in code</text>

  <rect class="step" x="580" y="130" width="170" height="56"/><text class="n" x="590" y="148">5</text><text class="t" x="604" y="148">Title + QC</text><text class="s" x="590" y="166">agent writes, server checks</text><text class="s" x="590" y="178">no spoilers, hook ≥ 3/5</text>
  <rect class="step you" x="390" y="130" width="170" height="56"/><text class="n" x="400" y="148">6</text><text class="t" x="414" y="148">You decide</text><text class="s" x="400" y="166">Team, or the video on Telegram</text><text class="s" x="400" y="178">Approve / Reject with a reason</text>
  <rect class="step you" x="200" y="130" width="170" height="56"/><text class="n" x="210" y="148">7</text><text class="t" x="224" y="148">Upload</text><text class="s" x="210" y="166">one press: by hand, or the API</text><text class="s" x="210" y="178">private, public at 06:00 Bangkok</text>
  <rect class="step you" x="10" y="130" width="170" height="56"/><text class="n" x="20" y="148">8</text><text class="t" x="34" y="148">Numbers come back</text><text class="s" x="20" y="166">Clips: % viewed, % swiped</text><text class="s" x="20" y="178">→ the next playbook knows</text>

  <path id="p1" class="flow" d="M180,48 L200,48"/>
  <path id="p2" class="flow" d="M370,48 L390,48"/>
  <path id="p3" class="flow" d="M560,48 L580,48"/>
  <path id="p4" class="flow" d="M665,76 L665,130"/>
  <path id="p5" class="flow" d="M580,158 L560,158"/>
  <path id="p6" class="flow" d="M390,158 L370,158"/>
  <path id="p7" class="flow" d="M200,158 L180,158"/>
  <path class="flow" d="M95,186 C95,250 95,250 380,250 C700,250 700,250 700,200" stroke-dasharray="4 4" marker-end="none"/>
  <text class="s" x="300" y="270">what worked and what did not, appended to the rules every agent reads</text>
  <circle r="5" fill="var(--key)">
    <animateMotion dur="9s" repeatCount="indefinite" path="M180,48 L200,48 L370,48 L390,48 L560,48 L580,48 L665,76 L665,130 L580,158 L560,158 L390,158 L370,158 L200,158 L180,158 L95,186 C95,250 95,250 380,250 C700,250 700,250 700,200"/>
  </circle>
</svg>

Steps 1, 6, 7 and 8 are yours. Everything between is measured before it is
judged: the gates cannot be argued with, the opinions can.

The stage a race runs on is measured before it ever reaches step 3. Stages
are stacked from sections (pegs, drums, belts, a funnel…), and `factory
stage-qa` races each one over dozens of seeds — stalls, parked marbles,
runner-ups, pace — before it is allowed into the random pick. The table is
on the **Stage QA** page.

## The daily loop, in practice

1. **Clips → Add work** — "make three marble races", or type
   `make 3 zigzag` / `plan L02..L04` in the command bar (⌘K). Or leave
   Claude's desk on **Team** on *auto* and just keep the queue fed.
2. **Team → Your decisions** — watch what came out, approve or reject (`A` / `R`), fix the
   opening caption if you want, **Copy for upload**, upload by hand, press
   **I uploaded it**. On the phone, the same clip arrives on Telegram with
   two buttons.
3. **Clips → published** — a few days later, enter the numbers from YouTube
   Studio on the row itself. Retitle what underperforms. The filter also
   shows the channel's totals. The next task an agent pulls already knows
   what worked.

## The screens

| screen | what you do there |
|---|---|
| **Team** (home) | the office. A briefing in plain words; **Your decisions** — review (`A` / `R` / `J` / `K`), run QC, publish, plan the next levels; **the office** — a desk per agent (Claude Code, Codex, any MCP agent) and per built-in brain, with what it is doing, what it did today, and start/stop for workers; below, **Records**: jobs and spend, what just happened, the activity log, how to connect an outside agent |
| **Season** | every level, what a blocked one waits for, planning, the standings table |
| **Clips** | one row per piece of work, queued to published — add work, hand it to an agent, view, download, bin. *In the bin* is a status: restore, or delete for good. Filter to *published* and the same screen shows how they did |
| **Settings** | this channel, its rules, the brains, the knobs, the themes, alerts — and these docs |

The **command bar** in the header (⌘K / Ctrl-K) runs the console by name,
with no model in between: `plan L02..L04`, `make 3 zigzag`, `import` (a
csv/json/yaml file of jobs, checked row by row before you confirm),
`run qc`, `build`, `publish`, `digest`, `open L05` or `open <clip id>`, and
`season` / `clips` / `settings`. Every write shows what it will do and runs
only on Enter. Old addresses (`#/today`, `#/agents`, `#/workers`,
`#/activity`) land on Team.

## How every screen is laid out

Title row, then a toolbar (search, filter chips, sort, a count), then the
content, then pagination. Every list comes from the server in one shape —
`items, total, page, page_size` — and the address bar carries the filters,
so refresh, back and a shared link land on the same view.

## Where things live

| what | where | in git? |
|---|---|---|
| the database, every render, the logs | `data/` | no — back this up |
| per-channel rules the agents read | `channels/` | yes |
| the prompts and skills | `prompts/` | yes |
| the knobs (also editable in Settings) | `config.toml` | yes |
| password, webhook, Telegram token | `.env` | never |
| YouTube OAuth client and per-channel tokens | `client_secrets.json`, `channels/<id>/token.json` | never |

The rest of these docs: **02** agents, the queue, workers and Telegram;
**03** clips, hooks and quality; **04** stages, sections, the arena and
themes; **05** deploying with Docker; **06** stage QA, the live numbers; **07**
YouTube: connecting a channel, what an upload sends, quota.
