# Start here

This is a small factory that makes short vertical clips from code — no camera,
no voice — and helps you decide which ones to publish. You spend about thirty
minutes a day on it, on one screen.

## The daily loop

1. **Clips → Add work** — "make three marble races". An agent (Codex,
   Claude Code, or the built-in one) pulls each task, renders the clip,
   writes a title, judges it, and reports back. The same row moves from
   *queued* to *rendering* to *to review* as it goes.
2. **Today** — what came out is waiting for you. Watch it, approve or reject
   (`A` / `R`), fix the opening caption if you want, then **Download**,
   upload by hand, and press **I uploaded it**.
3. **Results** — a few days later, enter the numbers from YouTube Studio.
   Retitle what underperforms. The next task an agent pulls already knows
   what worked.

## The screens

| screen | what you do there |
|---|---|
| **Today** | decide on what is waiting, then upload what you approved |
| **Clips** | one row per piece of work, queued to published — add work, hand it to an agent, view, download, bin |
| **Results** | how published clips did; enter metrics; retitle |
| **Activity** | what ran and what happened inside each run |
| **Bin** | what you threw away — restore, or delete for good |
| **Settings** | this channel, its rules, the brains, the knobs, the themes |
| **Docs** | this |

Every clip that passes the gates has been measured — length, loudness,
similarity to what already shipped — before any person or model formed an
opinion. The measurements cannot be argued with; the opinions can.

## How every screen is laid out

Title row, then a toolbar (search, filter chips, sort, a count), then the
content, then pagination. Every list comes from the server in one shape —
`items, total, page, page_size` — sorted by a field the server allows, 25, 50
or 100 to a page, and the filters live in the address bar
(`#/clips?status=published&sort=views&dir=desc&page=2`), so refresh, back and
a shared link agree. Errors and outcomes are toasts in the corner, never a
box in the way.

Settings is six tabs — Channel, Rules, Directions, Brains, Themes, Factory —
each with its own address. The Channel tab also picks the **market brief**: a file
under `prompts/market-*.md` (US ships) appended to everything an agent reads,
alongside your Directions (the Settings tab of that name).
