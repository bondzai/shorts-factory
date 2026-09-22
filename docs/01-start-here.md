# Start here

A small factory that makes short vertical clips from code — marble races, a
ball arena, coin ASMR — and helps you decide which ones to publish. Agents
do the making and judging; you do the deciding, about thirty minutes a day.

## How it fits together

Four lanes. You never talk to an agent directly: you add work, the server
holds it, whichever agent is around does it, and the result comes back to
you as a clip to approve.

<svg viewBox="0 0 760 420" xmlns="http://www.w3.org/2000/svg" font-family="ui-sans-serif, system-ui, sans-serif" font-size="12">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--dim)"/></marker>
    <style>
      .lane{fill:var(--panel);stroke:var(--line);rx:10}
      .lane-name{fill:var(--faint);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase}
      .card{fill:var(--bg);stroke:var(--line);stroke-width:1;rx:8}
      .card.key{stroke:var(--key)}
      .t{fill:var(--ink);font-weight:600}
      .s{fill:var(--dim);font-size:10.5px}
      .route{fill:none;stroke:var(--dim);stroke-width:1.3;marker-end:url(#arrow)}
      .route.key{stroke:var(--key)}
    </style>
  </defs>

  <rect class="lane" x="8" y="8" width="744" height="88"/>
  <text class="lane-name" x="20" y="24">You</text>
  <rect class="card key" x="24" y="34" width="150" height="48"/><text class="t" x="36" y="54">Console</text><text class="s" x="36" y="70">Today · Team · Clips · Results</text>
  <rect class="card" x="196" y="34" width="150" height="48"/><text class="t" x="208" y="54">Telegram</text><text class="s" x="208" y="70">clip + Approve / Reject</text>
  <rect class="card" x="368" y="34" width="150" height="48"/><text class="t" x="380" y="54">Discord / Slack</text><text class="s" x="380" y="70">what finished, daily reminder</text>
  <rect class="card" x="540" y="34" width="190" height="48"/><text class="t" x="552" y="54">YouTube</text><text class="s" x="552" y="70">by hand, or the API on your press</text>

  <rect class="lane" x="8" y="108" width="744" height="88"/>
  <text class="lane-name" x="20" y="124">Server · factory serve</text>
  <rect class="card key" x="24" y="134" width="120" height="48"/><text class="t" x="36" y="154">Web API</text><text class="s" x="36" y="170">FastAPI, one password</text>
  <rect class="card" x="164" y="134" width="120" height="48"/><text class="t" x="176" y="154">Task queue</text><text class="s" x="176" y="170">what was asked for</text>
  <rect class="card key" x="304" y="134" width="150" height="48"/><text class="t" x="316" y="154">Pipeline + gates</text><text class="s" x="316" y="170">render · measure · refuse</text>
  <rect class="card" x="474" y="134" width="120" height="48"/><text class="t" x="486" y="154">Workers</text><text class="s" x="486" y="170">starts the agent for you</text>
  <rect class="card" x="614" y="134" width="116" height="48"/><text class="t" x="626" y="154">Notify</text><text class="s" x="626" y="170">webhook · Telegram</text>

  <rect class="lane" x="8" y="208" width="744" height="88"/>
  <text class="lane-name" x="20" y="224">Agents · over MCP</text>
  <rect class="card key" x="24" y="234" width="200" height="48"/><text class="t" x="36" y="254">Claude Code / Codex</text><text class="s" x="36" y="270">next_task → render_clip → submit_qc → finish_task</text>
  <rect class="card" x="244" y="234" width="170" height="48"/><text class="t" x="256" y="254">factory mcp</text><text class="s" x="256" y="270">the tools, one process per agent</text>
  <rect class="card" x="434" y="234" width="160" height="48"/><text class="t" x="446" y="254">Built-in agents</text><text class="s" x="446" y="270">idea · metadata · QC · analyst (API key)</text>
  <rect class="card" x="614" y="234" width="116" height="48"/><text class="t" x="626" y="254">Playbooks</text><text class="s" x="626" y="270">prompts/*.md + skills</text>

  <rect class="lane" x="8" y="308" width="744" height="100"/>
  <text class="lane-name" x="20" y="324">Storage · data/ and the checkout</text>
  <rect class="card key" x="24" y="334" width="160" height="48"/><text class="t" x="36" y="354">SQLite</text><text class="s" x="36" y="370">clips · tasks · runs · settings</text>
  <rect class="card" x="204" y="334" width="150" height="48"/><text class="t" x="216" y="354">Renders</text><text class="s" x="216" y="370">data/work/&lt;channel&gt;/&lt;clip&gt;/clip.mp4</text>
  <rect class="card" x="374" y="334" width="150" height="48"/><text class="t" x="386" y="354">Event log</text><text class="s" x="386" y="370">data/logs/*.jsonl — the feed</text>
  <rect class="card" x="544" y="334" width="186" height="48"/><text class="t" x="556" y="354">config.toml · channels/ · .env</text><text class="s" x="556" y="370">knobs · rules · secrets (never in git)</text>

  <path class="route key" d="M99,82 L84,134"/>
  <path class="route" d="M534,182 L124,234"/>
  <path class="route" d="M329,234 L379,182"/>
  <path class="route key" d="M224,258 L244,258"/>
  <path class="route" d="M379,182 L379,152"/>
  <path class="route" d="M672,182 L440,82"/>
  <path class="route" d="M672,182 L271,82"/>
  <path class="route key" d="M84,182 L104,334"/>
  <path class="route" d="M379,182 L279,334"/>
  <path class="route" d="M379,182 L449,334"/>
  <path class="route" d="M99,82 L635,82" stroke-dasharray="4 4"/>
</svg>

Orange cards are the ones you will meet every day. The dotted line is the
step that never happens on its own: a clip reaches YouTube only when you
press the button. On a manual channel that means you upload the file and
press **I uploaded it**; with the YouTube driver connected (docs/07) the
same press uploads it, private, scheduled for the slot.

## One clip, start to finish

Eight steps. The dot walks them in order; every step leaves a row or an
event behind, so the Team screen and Telegram can tell you where a clip is
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
  <rect class="step you" x="390" y="130" width="170" height="56"/><text class="n" x="400" y="148">6</text><text class="t" x="414" y="148">You decide</text><text class="s" x="400" y="166">Today, or the video on Telegram</text><text class="s" x="400" y="178">Approve / Reject with a reason</text>
  <rect class="step you" x="200" y="130" width="170" height="56"/><text class="n" x="210" y="148">7</text><text class="t" x="224" y="148">Upload</text><text class="s" x="210" y="166">one press: by hand, or the API</text><text class="s" x="210" y="178">private, public at 06:00 Bangkok</text>
  <rect class="step you" x="10" y="130" width="170" height="56"/><text class="n" x="20" y="148">8</text><text class="t" x="34" y="148">Numbers come back</text><text class="s" x="20" y="166">Results: % viewed, % swiped</text><text class="s" x="20" y="178">→ the next playbook knows</text>

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

1. **Clips → Add work** — "make three marble races". Or leave **Team →
   Workers** on *auto* and just keep the queue fed.
2. **Today** — watch what came out, approve or reject (`A` / `R`), fix the
   opening caption if you want, **Copy for upload**, upload by hand, press
   **I uploaded it**. On the phone, the same clip arrives on Telegram with
   two buttons.
3. **Results** — a few days later, enter the numbers from YouTube Studio.
   Retitle what underperforms. The next task an agent pulls already knows
   what worked.

## The screens

| screen | what you do there |
|---|---|
| **Today** | decide on what is waiting, then upload what you approved |
| **Team** | every agent across every channel: what it holds, how far along, what it did today; start and stop workers; the log read out loud |
| **Clips** | one row per piece of work, queued to published — add work, hand it to an agent, view, download, bin |
| **Results** | how published clips did; enter metrics; retitle |
| **Activity** | what ran and what happened inside each run |
| **Bin** | what you threw away — restore, or delete for good |
| **Settings** | this channel, its rules, the brains, the knobs, the themes, alerts |
| **Docs** | this |

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
