# Running it somewhere else — and from an iPad

The factory is one process: FastAPI, SQLite, ffmpeg, a physics library. It
renders on the CPU (about a minute a clip) and keeps everything on local disk.
That shape decides what "free cloud" can honestly mean.

## First: a password

Set `FACTORY_PASSWORD` where the server runs and the page asks for it once
(a 90-day cookie; the API answers 401 without it). On this machine, bound to
127.0.0.1, it is not needed. The moment the page is reachable from anywhere
else it is required — there is no other lock on the door.

## Option A — keep the Mac as the server, reach it from the iPad (free, 10 minutes)

The Mac already renders clips and runs Codex. Put both devices on
[Tailscale](https://tailscale.com) (free for personal use), start the server
listening on the Tailscale interface, and open it from Safari on the iPad:

```bash
FACTORY_PASSWORD=choose-one factory serve --host 0.0.0.0
```

Then on the iPad: `http://<mac-tailscale-name>:8765`. Add it to the Home
Screen and it behaves like an app. Nothing leaves the Mac, there is nothing
to deploy, and the agents keep running where the files are. The one cost is
that the Mac has to be awake — set it never to sleep while plugged in.

This is the recommendation. Everything below trades simplicity for uptime.

## Option B — a free VM (Oracle Cloud Always Free)

The only free tier that fits a stateful renderer: an always-free ARM VM
(up to 4 cores, 24 GB) with a persistent disk. Render on it, keep SQLite on
it, back `data/` up yourself.

```bash
git clone git@github.com:bondzai/shorts-factory.git && cd shorts-factory
printf 'FACTORY_PASSWORD=choose-one\nFACTORY_WEBHOOK_URL=\nFACTORY_TELEGRAM_TOKEN=\nFACTORY_TELEGRAM_CHAT_ID=\n' > .env
docker compose up -d --build
```

The same three lines run it on the Mac. `docker-compose.yml` holds what
the image must not: `./data` (the database, every render, the logs) and
`./channels` are bind-mounted from the checkout, and `.env` is read at
start. So a rebuilt image is the same factory, and `./data` is the one
thing to back up — it is tens of megabytes. To move a factory between
machines, copy `data/`, `channels/` and `.env`; everything else is in git.

Two things stay outside the container by design. Agents (Codex, Claude
Code) run on the host and reach the factory over MCP, so `bin/cowork` still
uses the host's `.venv`; the container only serves the console and does
the rendering an agent asks for. And the daily reminder and the Telegram bot
run inside the container's server, so they work as long as the container is
up.

Put it behind Tailscale (private) or Caddy with HTTPS (public). Register the
MCP server for an agent on the VM, or run `factory work` from cron with a
free-tier provider (Settings → Brains) for `make-clip` tasks.

## Moving the factory to another machine (a mini PC, say)

`git clone` brings the code, the built console, the prompts, the docs and
`config.toml`. It deliberately does **not** bring the things below, because
they are yours, not the project's. Copy them by hand, then nothing has to be
set up twice:

| what | where | why it is not in git |
|---|---|---|
| the database — every clip, task, setting and metric | `data/factory.db` | your history |
| the rendered files | `data/out/`, `data/work/` | big, and reproducible from a seed |
| each channel's rules and directions | `channels/<id>/rules.md` | yours, edited on the Settings page |
| the password, Telegram and Discord secrets | `.env` | secrets |
| the YouTube credentials, per channel | `client_secrets.json`, `channels/<id>/token.json` | secrets |

Copy the database with the server **stopped** (it writes a `-wal` file beside
the `.db` while it runs), or take `data/factory.backup.db` if one is there —
a single-file snapshot written by the sqlite backup API, safe to copy while
the server is up. Put it in place as `data/factory.db`.

On the new machine:

    sudo apt install ffmpeg python3-venv        # or brew install ffmpeg
    python3 -m venv .venv && .venv/bin/pip install -e .
    .venv/bin/factory init                      # migrates the copied database
    .venv/bin/factory doctor                    # ffmpeg, deps, which brains are ready

For clips without a token bill, install Ollama from ollama.com/download and
pull the one model QC needs; `config.toml` already points the four brains
at it:

    ollama pull qwen2.5vl:7b                    # about 6 GB
    .venv/bin/factory brains --test ollama      # one round trip, before a clip finds out

Then `factory serve --host 0.0.0.0 --port 8765` with `FACTORY_PASSWORD` in
`.env`, and **Build planned** on the console makes clips with no key at all.
On a small CPU the model is the wait, not the render: a clip renders in
seconds, a 7B model answers in tens of seconds to minutes. See docs/02 for
what the template takes off that bill.

## What does not fit

Render, Railway, Fly and Cloud Run free tiers either sleep, have no
persistent disk, or bill for CPU minutes — a renderer that works for a minute
per clip and keeps a database is exactly the shape they are not for. Hugging
Face Spaces runs the container for free but its disk is ephemeral. If you
want one of these anyway, the database needs to move to a hosted one and
the renders to object storage; that is a different project.

## From the iPad

The console is touch-friendly: bigger targets, no keyboard shortcuts shown,
the nav folds to the top. Review, approve, re-render, download and "I
uploaded it" all work in Safari — Download saves to Files, from where the
YouTube app can upload. What the iPad cannot do is run Codex; the agents run
where the server runs.

## YouTube from a container

The OAuth flow opens a browser, which a container does not have. Connect a
channel on your own machine first (`factory youtube connect`), then copy
`channels/<id>/token.json` and `client_secrets.json` into the volume the
container mounts. Refreshing an existing token needs no browser, so uploads
keep working there; only the first connect does.
