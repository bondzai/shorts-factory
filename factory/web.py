"""Local web UI for the daily loop, across every channel.

The command line is fine for plan, build and publish, but not for the fifteen
minutes that matter: deciding. You cannot judge a hook by reading a row in a
table — you have to watch the first second. So the queue here is a stack of
clips that play, with approve and reject one keystroke away.

Every request names a channel. One page switches between them; nothing is
shared but the code.

Binds to 127.0.0.1 only. There is no authentication and none is wanted; this
reads your database and spends your API credit.
"""

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics, channels, db, generators, llm, logs, pipeline, playbooks, settings, tasks, themes
from .agents import analyst
from .models import APPROVED, AWAITING_APPROVAL, PLANNED, PUBLISHED

STATIC = Path(__file__).resolve().parent / "static"


class _Job:
    """One background task at a time, with a log the page can poll.

    Deliberately not a queue: two builds at once would fight over the same clip
    rows. The channel is part of the job so the page can tell you that the thing
    blocking you is a build on another channel.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name: str | None = None
        self.channel_id: str | None = None
        self.log: list[str] = []
        self.finished_at: str | None = None

    @property
    def running(self) -> bool:
        return self.name is not None

    def start(
        self, name: str, channel_id: str, work: Callable[[Callable[[str], None]], float]
    ) -> None:
        with self.lock:
            if self.running:
                raise HTTPException(
                    409, f"{self.name} is already running on {self.channel_id}"
                )
            self.name = name
            self.channel_id = channel_id
            self.log = []
            self.finished_at = None

        def emit(line: str) -> None:
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            self.log.append(f"{stamp}  {line}")

        def run() -> None:
            with db.connect() as conn:
                run_id = db.start_run(conn, channel_id, name)
            status, cost = "ok", 0.0
            try:
                cost = work(emit) or 0.0
            except Exception as exc:
                status = "failed"
                emit(f"failed: {exc}")
                emit(traceback.format_exc().strip().splitlines()[-1])
            finally:
                with db.connect() as conn:
                    db.finish_run(
                        conn, run_id, status=status,
                        detail=self.log[-1] if self.log else "",
                        log="\n".join(self.log[-60:]), cost_usd=cost,
                    )
                with self.lock:
                    self.name = None
                    self.channel_id = None
                    self.finished_at = db.now()

        threading.Thread(target=run, daemon=True).start()

    def state(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "name": self.name,
            "channel_id": self.channel_id,
            "log": self.log[-60:],
            "finished_at": self.finished_at,
        }


JOB = _Job()
app = FastAPI(title="shorts-factory", docs_url=None, redoc_url=None)


# --- a password gate, only when FACTORY_PASSWORD is set ------------------------
# On this machine the page is bound to 127.0.0.1 and needs nothing. The moment
# it is reachable from elsewhere — a tablet over Tailscale, a VM on the
# internet — it needs a door. One shared password, a signed cookie, no
# accounts: it is one operator's console, not a product.

import hashlib
import hmac
import os
import secrets

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

COOKIE = "factory_session"


def _password() -> str | None:
    settings.load_env()
    return os.environ.get("FACTORY_PASSWORD") or None


def _token(password: str) -> str:
    return hmac.new(password.encode(), b"factory-session-v1", hashlib.sha256).hexdigest()


LOGIN_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<link rel=icon type=image/svg+xml href=/static/logo.svg><title>shorts factory</title><style>body{margin:0;background:#12121a;color:#e8e8ef;font:16px system-ui;display:grid;place-items:center;min-height:100vh}@media(prefers-color-scheme:light){body{background:#f7f7fa;color:#1b1b26}}
form{display:grid;gap:12px;width:min(320px,90vw)}input,button{font:inherit;padding:12px;border-radius:10px;border:1px solid #2b2b38;background:#1a1a24;color:inherit}@media(prefers-color-scheme:light){input{border-color:#d9d9e2;background:#fff}}b{display:flex;align-items:center;gap:8px}b img{width:26px;height:26px}
button{background:#efa027;color:#412402;border:0;font-weight:600}p{color:#8f8fa3;margin:0}</style>
<form method=post action=/login><b><img src=/static/logo.svg alt="">shorts factory</b><p>%s</p><input type=password name=password placeholder=password autofocus><button>Open</button></form>"""


@app.middleware("http")
async def _gate(request: Request, call_next):
    password = _password()
    # The login page needs the built assets to render; everything else waits.
    if not password or request.url.path == "/login" or request.url.path.startswith(("/static/", "/assets/")):
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get(COOKIE, ""), _token(password)):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return Response('{"detail":"sign in first"}', status_code=401, media_type="application/json")
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    return LOGIN_PAGE % "One password, set as FACTORY_PASSWORD where the server runs."


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    password = _password()
    if password and secrets.compare_digest(str(form.get("password", "")), password):
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, _token(password), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
        return response
    return HTMLResponse(LOGIN_PAGE % "That is not it.", status_code=401)


def _resolve(conn, channel_id: str | None):
    try:
        return channels.resolve(conn, channel_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from None


def _clip_json(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "channel_id": row["channel_id"],
        "generator": row["generator"],
        "variant": row["variant"],
        "seed": row["seed"],
        "status": row["status"],
        "hook": row["hook"],
        "why": row["plan_why"],
        "title": row["title"],
        "description": row["description"],
        "hashtags": json.loads(row["hashtags_json"] or "[]"),
        "render_desc": row["render_desc"],
        "duration_s": row["duration_s"],
        "loudness_lufs": row["loudness_lufs"],
        "sameness": row["sameness"],
        "cost_usd": row["cost_usd"],
        "qc": json.loads(row["qc_json"] or "null"),
        "reject_reason": row["reject_reason"],
        "has_video": bool(row["video_path"]),
        "hook_text": row["hook_text"],
        "comment_prompt": row["comment_prompt"],
        "title_history": json.loads(row["title_history_json"] or "[]"),
        "published_at": row["published_at"],
        "facts": {k: v for k, v in json.loads(row["facts_json"] or "{}").items() if k in ("course", "theme", "backdrop", "margin_s", "winner")},
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")

# The console is a Vite build in static/dist (source under web/). Its hashed
# assets are served from /assets, the page from /. The build is committed, so
# nothing at runtime needs node; `npm run build` in web/ refreshes it.
DIST = STATIC / "dist"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    page = DIST / "index.html"
    if not page.exists():
        raise HTTPException(503, "the console is not built: run `npm install && npm run build` in web/")
    return page.read_text()


@app.get("/api/channels")
def list_channels() -> dict[str, Any]:
    with db.connect() as conn:
        out = []
        for channel in channels.all_channels(conn):
            counts = db.status_counts(conn, channel.id)
            out.append(
                {
                    **channel.as_dict(),
                    "counts": counts,
                    "spend_usd": db.spend(conn, channel.id),
                    "queue": counts.get(AWAITING_APPROVAL, 0),
                }
            )
    return {"channels": out}


class ChannelBody(BaseModel):
    name: str
    id: str | None = None
    handle: str | None = None
    platform: str = "youtube"
    driver: str | None = None
    variants: list[str] = []
    cadence: int = 1


@app.post("/api/channels")
def create_channel(body: ChannelBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            channel = channels.create(
                conn,
                name=body.name,
                channel_id=body.id,
                handle=body.handle,
                platform=body.platform,
                driver=body.driver,
                variants=body.variants,
                cadence=body.cadence,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return channel.as_dict()


class ChannelEdit(BaseModel):
    name: str | None = None
    handle: str | None = None
    driver: str | None = None
    variants: list[str] | None = None
    cadence: int | None = None
    active: bool | None = None


@app.patch("/api/channels/{channel_id}")
def edit_channel(channel_id: str, body: ChannelEdit) -> dict[str, Any]:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "active" in fields:
        fields["active"] = int(fields["active"])
    with db.connect() as conn:
        try:
            channel = channels.edit(conn, channel_id, **fields)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from None
    return channel.as_dict()


@app.get("/api/state")
def state(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        counts = db.status_counts(conn, ch.id)
        return {
            "channel": ch.as_dict(),
            "counts": counts,
            "queue": [_clip_json(r) for r in db.by_status(conn, ch.id, AWAITING_APPROVAL)],
            "approved": [_clip_json(r) for r in db.by_status(conn, ch.id, APPROVED)],
            "planned": counts.get(PLANNED, 0),
            "recent": [_clip_json(r) for r in db.recent(conn, ch.id, 12)],
            "runs": [dict(r) for r in db.recent_runs(conn, ch.id, 8)],
            "spend_usd": db.spend(conn, ch.id),
            "spend_total_usd": db.spend(conn),
            "job": JOB.state(),
            # Two brains can drive this factory: the built-in agents (need a
            # key) or an external one over MCP (needs nothing). The page
            # shows the buttons for whichever can actually do something.
            "agents": {"available": llm.has_credentials()},
            "tasks": db.task_counts(conn, ch.id),
        }


@app.get("/api/playbooks")
def list_playbooks() -> dict[str, Any]:
    return {"playbooks": playbooks.available()}


@app.get("/api/playbook/{name}")
def get_playbook(name: str, channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
    try:
        return {"name": name, "channel": ch.id, "text": playbooks.render(name, ch.id)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


class IdsBody(BaseModel):
    ids: list[str]


# --- the task queue -----------------------------------------------------------

@app.get("/api/tasks")
def list_tasks(
    channel: str | None = None, status: str | None = None, kind: str | None = None, q: str | None = None,
    sort: str | None = None, dir: str | None = None, page: int = 1, page_size: int = 25,
) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        rows, total = db.tasks(conn, ch.id, status, kind=kind, query=q, sort=sort, direction=dir,
                               page=page, page_size=page_size)
        counts = db.task_counts(conn, ch.id)
    items = [tasks.as_dict(r) for r in rows]
    p, size = db.page_args(page, page_size)
    return {
        "items": items, "total": total, "page": p, "page_size": size,
        "tasks": items,
        "counts": counts,
        "kinds": {k: {"meaning": v["meaning"], "params": v["params"], "builtin": v["builtin"]} for k, v in tasks.KINDS.items()},
    }


class TaskBody(BaseModel):
    channel: str | None = None
    kind: str
    params: dict[str, Any] = {}
    count: int = 1
    priority: int = 0


@app.post("/api/tasks")
def add_tasks(body: TaskBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        try:
            ids = tasks.enqueue(conn, ch.id, body.kind, body.params, count=body.count, priority=body.priority)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"ids": ids}


@app.delete("/api/tasks/{task_id}")
def cancel_task(task_id: int) -> dict[str, str]:
    with db.connect() as conn:
        try:
            db.cancel_task(conn, task_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": "cancelled"}


class TaskIdsBody(BaseModel):
    ids: list[int]


@app.post("/api/tasks/delete")
def delete_tasks(body: TaskIdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        removed = db.delete_tasks(conn, body.ids)
    logs.event("task.deleted", ids=removed, by="human")
    return {"deleted": removed}


@app.post("/api/tasks/cancel")
def cancel_tasks(body: TaskIdsBody) -> dict[str, Any]:
    cancelled = []
    with db.connect() as conn:
        for task_id in body.ids:
            try:
                db.cancel_task(conn, task_id); cancelled.append(task_id)
            except ValueError:
                continue
    return {"cancelled": cancelled}


class TaskClearBody(BaseModel):
    channel: str | None = None


@app.post("/api/tasks/clear")
def clear_tasks(body: TaskClearBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        n = db.clear_finished_tasks(conn, ch.id)
    logs.event("task.cleared", channel=ch.id, count=n, by="human")
    return {"cleared": n}


@app.post("/api/tasks/work")
def work_tasks(body: ChannelOnly) -> dict[str, Any]:
    """Run the queue with the built-in agents, as a job."""
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def run(emit) -> float:
        with db.connect() as conn:
            emit(f"{ch.name}: working the queue with the built-in agents")
            try:
                done = tasks.work(conn, channel_id=ch.id)
            except ValueError as exc:
                emit(str(exc)); return 0.0
            for t in done:
                emit(f"task #{t['id']} {t['kind']}: {t['status']} {t.get('error') or (t.get('result') or {}).get('detail', '')}")
            emit(f"{len(done)} task(s) done")
            return sum((t.get("result") or {}).get("cost_usd", 0.0) for t in done)

    JOB.start("work", ch.id, run)
    return JOB.state()


# --- settings: what config.toml says, what the page changed, and the schema ---

def _coerce(field: dict[str, Any], value: Any) -> Any:
    if field["type"] == "number":
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field['label']}: not a number") from None
        if "min" in field and value < field["min"] or "max" in field and value > field["max"]:
            raise ValueError(f"{field['label']}: must be between {field['min']} and {field['max']}")
        return int(value) if float(value).is_integer() and field.get("step", 1) == 1 else value
    if field["type"] == "select":
        for option in field["options"]:
            if str(option) == str(value):
                return option
        raise ValueError(f"{field['label']}: must be one of {field['options']}")
    return str(value)


def _settings_view() -> dict[str, Any]:
    cfg = settings.load()
    fields = []
    for f in settings.SCHEMA:
        key = (f["section"], f["key"])
        fields.append({
            **f,
            "value": cfg.raw.get(f["section"], {}).get(f["key"]),
            "default": cfg.base.get(f["section"], {}).get(f["key"]),
            "overridden": key in cfg.overrides,
        })
    return {"fields": fields}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return _settings_view()


class SettingBody(BaseModel):
    section: str
    key: str
    value: Any


@app.put("/api/settings")
def put_setting(body: SettingBody) -> dict[str, Any]:
    field = next((f for f in settings.SCHEMA if f["section"] == body.section and f["key"] == body.key), None)
    if field is None:
        raise HTTPException(404, f"no setting {body.section}.{body.key}")
    try:
        value = _coerce(field, body.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    with db.connect() as conn:
        db.set_override(conn, body.section, body.key, value)
    settings.invalidate()
    logs.event("settings.changed", section=body.section, key=body.key, value=value, by="human")
    return _settings_view()


@app.delete("/api/settings/{section}/{key}")
def reset_setting(section: str, key: str) -> dict[str, Any]:
    with db.connect() as conn:
        db.clear_override(conn, section, key)
    settings.invalidate()
    logs.event("settings.reset", section=section, key=key, by="human")
    return _settings_view()


# --- directions: what every agent is told, editable without touching a playbook

@app.get("/api/market")
def get_market(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        return {"channel": ch.id, "market": playbooks.market_for(conn, ch.id), "markets": playbooks.markets()}


class MarketBody(BaseModel):
    channel: str | None = None
    market: str


@app.put("/api/market")
def put_market(body: MarketBody) -> dict[str, Any]:
    if body.market and body.market not in playbooks.markets():
        raise HTTPException(400, f"no market brief {body.market!r}; have {playbooks.markets()} (add prompts/market-<id>.md)")
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        db.set_override(conn, "market", ch.id, body.market)
    logs.event("settings.changed", section="market", key=ch.id, market=body.market, by="human")
    return get_market(ch.id)


@app.get("/api/directions")
def get_directions(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        values = playbooks.directions(conn, ch.id)
    return {
        "channel": ch.id,
        "fields": [{"key": k, "label": label, "placeholder": hint, "value": values[k]} for k, label, hint in playbooks.DIRECTION_FIELDS],
    }


class DirectionsBody(BaseModel):
    channel: str | None = None
    values: dict[str, str]


@app.put("/api/directions")
def put_directions(body: DirectionsBody) -> dict[str, Any]:
    allowed = {k for k, _, _ in playbooks.DIRECTION_FIELDS}
    unknown = set(body.values) - allowed
    if unknown:
        raise HTTPException(400, f"no such direction: {sorted(unknown)}")
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        clean = {k: v.strip()[:600] for k, v in body.values.items()}
        db.set_override(conn, "directions", ch.id, clean)
    logs.event("settings.changed", section="directions", key=ch.id, by="human")
    return get_directions(ch.id)


# --- themes: seasons, as data the page can edit ---------------------------------

def _themes_view() -> dict[str, Any]:
    from datetime import date

    today = date.today()
    cfg = settings.load()
    return {
        "themes": [t.as_dict() for t in themes.themes()],
        "active": themes.active(today).id,
        "today": today.isoformat(),
        "force": (cfg.raw.get("themes", {}).get("force") or ""),
        "decorations": list(themes.DECORATIONS),
        "overridden": ("themes", "list") in cfg.overrides or ("themes", "force") in cfg.overrides,
    }


@app.get("/api/themes")
def get_themes() -> dict[str, Any]:
    return _themes_view()


class ThemesBody(BaseModel):
    themes: list[dict[str, Any]]
    force: str = ""


@app.put("/api/themes")
def put_themes(body: ThemesBody) -> dict[str, Any]:
    try:
        parsed = [themes.from_dict(t) for t in body.themes]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    ids = [t.id for t in parsed]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "two themes share an id")
    if body.force and body.force not in ids and body.force != "default":
        raise HTTPException(400, f"cannot force {body.force!r}: not a theme here")
    with db.connect() as conn:
        db.set_override(conn, "themes", "list", [t.as_dict() for t in parsed])
        db.set_override(conn, "themes", "force", body.force)
    settings.invalidate()
    logs.event("settings.changed", section="themes", key="list", force=body.force, by="human")
    # Echo what was just saved rather than re-reading: the read is right too,
    # but the page should never see a stale value for the thing it just set.
    return {**_themes_view(), "themes": [t.as_dict() for t in parsed], "force": body.force, "overridden": True}


# --- docs: the hand-written pages plus a reference generated from the code ----

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _reference() -> str:
    from .generators import physics
    from . import cli

    lines = ["# Reference", "", "Generated from the code at the moment you opened this page, so it cannot be stale.", ""]
    lines += ["## Settings the page can change", "", "| section | key | type | range | meaning |", "|---|---|---|---|---|"]
    for f in settings.SCHEMA:
        rng = f"{f['min']}–{f['max']}" if "min" in f else (", ".join(str(o) for o in f["options"]) if "options" in f else "")
        lines.append(f"| {f['section']} | `{f['key']}` | {f['type']} | {rng} | {f['label']}{' — ' + f['help'] if f.get('help') else ''} |")
    lines += ["", "## Task kinds", "", "| kind | meaning | parameters | built-in agents can do it |", "|---|---|---|---|"]
    for k, v in tasks.KINDS.items():
        lines.append(f"| `{k}` | {v['meaning']} | {', '.join(v['params']) or '—'} | {'yes' if v['builtin'] else 'no'} |")
    lines += ["", "## Courses", "", "| course | weight | gravity |", "|---|---|---|"]
    for c, w in physics.COURSES.items():
        lines.append(f"| `{c}` | {w} | {physics.COURSE_GRAVITY[c]} |")
    lines += ["", "## Themes", "", "| id | window | decoration | marbles |", "|---|---|---|---|"]
    for t in themes.themes():
        lines.append(f"| `{t.id}` | {'–'.join(t.window) if t.window else 'default'} | {t.decoration} | {', '.join(n for n, _ in t.marbles)} |")
    lines += ["", "## Playbooks", "", *[f"- `{n}`" for n in playbooks.available()]]
    lines += ["", "## Commands", "", "```"]
    parser = cli.build_parser()
    for action in parser._subparsers._group_actions:  # noqa: SLF001 - argparse has no public walk
        for name, sub in action.choices.items():
            lines.append(f"factory {name:14s} {sub.description or ''}")
    lines += ["```", ""]
    return "\n".join(lines)


@app.get("/api/docs")
def list_docs() -> dict[str, Any]:
    pages = []
    for path in sorted(DOCS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = next((l[2:] for l in text.splitlines() if l.startswith("# ")), path.stem)
        pages.append({"id": path.stem, "title": title, "text": text})
    pages.append({"id": "reference", "title": "Reference", "text": _reference()})
    return {"pages": pages}


# --- brains: which model each built-in agent runs on ---------------------------

def _brains_view() -> dict[str, Any]:
    return {
        "providers": [{**p.as_dict(), "key_present": p.key_present()} for p in llm.providers()],
        "agents": {a: llm.assignment(a) for a in llm.AGENTS},
        "readiness": llm.readiness(),
        "needs_vision": sorted(llm.NEEDS_VISION),
        "presets": llm.PRESETS,
        "mcp_command": [str(settings.ROOT / ".venv" / "bin" / "factory"), "mcp"],
        "overridden": any(k[0] == "llm" for k in settings.load().overrides),
    }


@app.get("/api/brains")
def get_brains() -> dict[str, Any]:
    return _brains_view()


class BrainsBody(BaseModel):
    providers: list[dict[str, Any]]
    agents: dict[str, str]


@app.put("/api/brains")
def put_brains(body: BrainsBody) -> dict[str, Any]:
    try:
        parsed = [llm._provider_from(p) for p in body.providers]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    ids = [p.id for p in parsed]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "two providers share an id")
    by_id = {p.id: p for p in parsed}
    for agent, chosen in body.agents.items():
        if agent not in llm.AGENTS:
            raise HTTPException(400, f"no agent {agent!r}; have {list(llm.AGENTS)}")
        pid, _, model = chosen.partition("/")
        if pid not in by_id or not model:
            raise HTTPException(400, f"{agent}: choose provider/model, e.g. anthropic/claude-sonnet-5")
        if agent in llm.NEEDS_VISION and not by_id[pid].vision:
            raise HTTPException(400, f"{agent} judges frames; {pid} is marked as unable to see images")
    with db.connect() as conn:
        db.set_override(conn, "llm", "providers", [p.as_dict() for p in parsed])
        db.set_override(conn, "llm", "agents", body.agents)
    settings.invalidate()
    llm._openai_client.cache_clear()
    logs.event("settings.changed", section="llm", key="brains", agents=body.agents, by="human")
    return _brains_view()


class TestBody(BaseModel):
    provider: str
    model: str | None = None


@app.post("/api/brains/test")
def test_brain(body: TestBody) -> dict[str, Any]:
    return llm.test_provider(body.provider, body.model)


@app.post("/api/clips/bin")
def bin_clips(body: IdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            return {"binned": pipeline.bin_clips(conn, body.ids)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None


@app.post("/api/clips/unbin")
def unbin_clips(body: IdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            return {"restored": pipeline.unbin_clips(conn, body.ids)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None


@app.post("/api/clips/destroy")
def destroy_clips(body: IdsBody) -> dict[str, Any]:
    with db.connect() as conn:
        try:
            return {"destroyed": pipeline.destroy_clips(conn, body.ids)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None


@app.get("/api/work")
def work(
    channel: str | None = None, stage: str | None = None, variant: str | None = None, q: str | None = None,
    sort: str | None = None, dir: str | None = None, page: int = 1, page_size: int = 25,
) -> dict[str, Any]:
    """Tasks and clips as one list. Each item says which it is (row_kind) and
    where it is (stage); a task item is tasks.as_dict, a clip item is the
    same shape /api/clips gives, so the page needs no third kind of row."""
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        rows, total, counts = db.work(conn, ch.id, stage=stage, variant=variant, query=q,
                                      sort=sort, direction=dir, page=page, page_size=page_size)
        items = []
        for w in rows:
            if w["row_kind"] == "task":
                t = db.get_task(conn, int(w["task_id"]))
                if t is None:
                    continue
                items.append({**tasks.as_dict(t), "row_kind": "task", "stage": w["stage"], "key": w["id"]})
            else:
                row = db.get(conn, w["clip_id"])
                if row is None:
                    continue
                items.append({
                    **_clip_json(row), "row_kind": "clip", "stage": w["stage"], "key": w["id"],
                    "created_at": row["created_at"], "views": row["views"],
                    "avg_view_pct": row["avg_view_pct"], "swipe_away_pct": row["swipe_away_pct"],
                })
        binned = conn.execute(
            "SELECT COUNT(*) n FROM clips WHERE channel_id = ? AND deleted_at IS NOT NULL", (ch.id,)
        ).fetchone()["n"]
        modules = generators.available(ch.variants)
    p, size = db.page_args(page, page_size)
    return {
        "items": items, "total": total, "page": p, "page_size": size,
        "stages": [{"id": s, "count": counts.get(s, 0)} for s in db.STAGES if counts.get(s)],
        "modules": modules, "binned": binned,
        "kinds": {k: {"meaning": v["meaning"], "params": v["params"], "builtin": v["builtin"]} for k, v in tasks.KINDS.items()},
    }


@app.get("/api/clips")
def clips(
    channel: str | None = None,
    status: str | None = None,
    generator: str | None = None,
    variant: str | None = None,
    q: str | None = None,
    bin: bool = False,
    sort: str | None = None,
    dir: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        rows, total = db.search_clips(
            conn, ch.id, status=status, generator=generator, variant=variant, query=q,
            binned=bin, sort=sort, direction=dir, page=page, page_size=page_size,
        )
        counts = db.status_counts(conn, ch.id)
        binned = conn.execute(
            "SELECT COUNT(*) n FROM clips WHERE channel_id = ? AND deleted_at IS NOT NULL", (ch.id,)
        ).fetchone()["n"]
    items = [
        {
            **_clip_json(row),
            "created_at": row["created_at"],
            "published_at": row["published_at"],
            "views": row["views"],
            "avg_view_pct": row["avg_view_pct"],
            "swipe_away_pct": row["swipe_away_pct"],
            "deleted_at": row["deleted_at"],
        }
        for row in rows
    ]
    p, size = db.page_args(page, page_size)
    return {
        "items": items, "total": total, "page": p, "page_size": size,
        "clips": items,  # the previous name; the page reads `items`
        "counts": counts,
        "binned": binned,
        # The filter chips are built from this, so a new generator module
        # appears in the UI without the page knowing its name.
        "modules": generators.available(ch.variants),
        "statuses": sorted(counts),
    }


@app.get("/api/analytics")
def analytics_summary(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        return analytics.summary(conn, ch.id)


@app.get("/api/runs")
def runs(channel: str | None = None, status: str | None = None, kind: str | None = None,
         sort: str | None = None, dir: str | None = None, page: int = 1, page_size: int = 25) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        rows, total = db.runs_page(conn, ch.id, status=status, kind=kind, sort=sort, direction=dir,
                                   page=page, page_size=page_size)
    items = [dict(r) for r in rows]
    p, size = db.page_args(page, page_size)
    return {"items": items, "total": total, "page": p, "page_size": size, "runs": items}


@app.get("/api/logs")
def read_logs(
    channel: str | None = None,
    level: str | None = None,
    event: str | None = None,
    q: str | None = None,
    limit: int = 120,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """The event log is files, not SQL: read a generous window, filter, then page."""
    with db.connect() as conn:
        ch = _resolve(conn, channel)
    events = logs.read(limit=max(limit, page * page_size, 2000), channel=ch.id, level=level, event_name=event)
    if q:
        needle = q.lower()
        events = [e for e in events if needle in json.dumps(e, default=str).lower()]
    p, size = db.page_args(page, page_size)
    items = events[(p - 1) * size : p * size]
    return {"items": items, "total": len(events), "page": p, "page_size": size, "events": events[:limit]}


@app.get("/api/rules")
def get_rules(channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, channel)
        latest = db.latest_digest(conn, ch.id)
        text = ch.rules()
    proposals = json.loads(latest["proposals_json"]) if latest else []
    return {
        "channel_id": ch.id,
        # Relative to the repo: the absolute path is long, machine-specific and
        # tells the reader nothing they need.
        "path": str(ch.rules_path.relative_to(settings.ROOT)),
        "text": text,
        "proposals": [p for p in proposals if p not in text],
        "digest": (
            {
                "created_at": latest["created_at"],
                "n_published": latest["n_published"],
                "body": latest["body"],
            }
            if latest
            else None
        ),
    }


class RulesBody(BaseModel):
    channel: str | None = None
    text: str


@app.put("/api/rules")
def put_rules(body: RulesBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        ch.rules()  # make sure the file exists before overwriting it
        ch.rules_path.write_text(body.text)
    return {"path": str(ch.rules_path), "bytes": len(body.text)}


class AcceptBody(BaseModel):
    channel: str | None = None
    rules: list[str]


@app.post("/api/rules/accept")
def accept_rules(body: AcceptBody) -> dict[str, Any]:
    """Append chosen proposals to this channel's rules, one at a time."""
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)
        ch.rules()
        try:
            applied = analyst.apply_rules(body.rules, ch.rules_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"applied": applied, "text": ch.rules_path.read_text()}


@app.get("/api/clip/{clip_id}")
def clip_detail(clip_id: str) -> dict[str, Any]:
    """Everything the page knows about one clip, for viewing without downloading."""
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    if row is None:
        raise HTTPException(404, f"no clip {clip_id}")
    path = Path(row["video_path"]) if row["video_path"] else None
    return {
        **_clip_json(row),
        "facts": json.loads(row["facts_json"] or "{}"),
        "params": json.loads(row["params_json"] or "{}"),
        "created_at": row["created_at"],
        "published_at": row["published_at"],
        "deleted_at": row["deleted_at"],
        "purged_at": row["purged_at"],
        "views": row["views"],
        "avg_view_pct": row["avg_view_pct"],
        "swipe_away_pct": row["swipe_away_pct"],
        "likes": row["likes"],
        "metrics_at": row["metrics_at"],
        "file": {
            "path": str(path.relative_to(settings.ROOT)) if path and path.is_relative_to(settings.ROOT) else (str(path) if path else None),
            "exists": bool(path and path.exists()),
            "mb": round(path.stat().st_size / 1e6, 2) if path and path.exists() else None,
        },
    }


@app.get("/api/clip/{clip_id}/video")
def video(clip_id: str, download: bool = False) -> FileResponse:
    with db.connect() as conn:
        row = db.get(conn, clip_id)
    if row is None or not row["video_path"]:
        raise HTTPException(404, "no video for that clip")
    path = Path(row["video_path"])
    if not path.exists():
        raise HTTPException(410, f"file is gone: {path}")
    if download:
        # A name you can find in the upload dialog, not clip.mp4 twelve times.
        return FileResponse(
            path, media_type="video/mp4",
            filename=f"{row['variant']}-{row['seed']}-{clip_id[:6]}.mp4",
        )
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/clip/{clip_id}/publish")
def publish_clip(clip_id: str) -> dict[str, str]:
    """The "I uploaded it" button on a manual channel."""
    with db.connect() as conn:
        try:
            outcome = pipeline.publish_one(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    if outcome.status != PUBLISHED:
        raise HTTPException(500, outcome.detail)
    return {"status": outcome.status, "detail": outcome.detail}


class PlanBody(BaseModel):
    channel: str | None = None
    count: int = 3


@app.post("/api/plan")
def plan(body: PlanBody) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        emit(f"{ch.name}: asking the Idea agent for {body.count} clip(s)")
        with db.connect() as conn:
            ids, cost = pipeline.plan(conn, ch, body.count)
            for clip_id in ids:
                row = db.get(conn, clip_id)
                emit(f"{clip_id}  {row['generator']}/{row['variant']}  {row['hook']}")
        emit(f"planned {len(ids)}, ${cost:.4f}")
        return cost

    JOB.start("plan", ch.id, work)
    return JOB.state()


class ChannelOnly(BaseModel):
    channel: str | None = None


@app.post("/api/build")
def build(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        with db.connect() as conn:
            planned = db.by_status(conn, ch.id, PLANNED)
            if not planned:
                emit("nothing planned")
                return 0.0
            emit(f"{ch.name}: building {len(planned)} clip(s)")
            spend = 0.0
            for row in planned:
                emit(f"{row['id']}  rendering {row['generator']}/{row['variant']}...")
                outcome = pipeline.build(conn, row["id"])
                spend += outcome.cost_usd
                emit(f"{row['id']}  {outcome.status}: {outcome.detail}")
            emit(f"done, ${spend:.4f}")
            return spend

    JOB.start("build", ch.id, work)
    return JOB.state()


@app.post("/api/publish")
def publish(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        with db.connect() as conn:
            outcomes = pipeline.publish_approved(conn, ch)
        if not outcomes:
            emit("nothing approved")
        for outcome in outcomes:
            emit(f"{outcome.clip_id}  {outcome.status}: {outcome.detail}")
        return 0.0

    JOB.start("publish", ch.id, work)
    return JOB.state()


@app.post("/api/digest")
def digest(body: ChannelOnly) -> dict[str, Any]:
    with db.connect() as conn:
        ch = _resolve(conn, body.channel)

    def work(emit) -> float:
        with db.connect() as conn:
            text, cost, _ = pipeline.digest(conn, ch, apply_rules=False)
        for line in text.splitlines():
            emit(line)
        emit(f"${cost:.4f}")
        return cost

    JOB.start("digest", ch.id, work)
    return JOB.state()


@app.post("/api/clip/{clip_id}/approve")
def approve(clip_id: str) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.approve(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": APPROVED}


class RejectBody(BaseModel):
    reason: str = "not good enough"


@app.post("/api/clip/{clip_id}/restore")
def restore(clip_id: str) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.restore(conn, clip_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": AWAITING_APPROVAL}


class TextBody(BaseModel):
    title: str | None = None
    comment_prompt: str | None = None
    why: str = ""


@app.patch("/api/clip/{clip_id}/text")
def edit_text(clip_id: str, body: TextBody) -> dict[str, Any]:
    out: dict[str, Any] = {"clip": clip_id}
    with db.connect() as conn:
        try:
            if body.title is not None:
                out = pipeline.retitle(conn, clip_id, body.title, by="human", why=body.why)
            if body.comment_prompt is not None:
                if db.get(conn, clip_id) is None:
                    raise ValueError(f"no clip {clip_id}")
                db.update(conn, clip_id, comment_prompt=body.comment_prompt.strip() or None)
                out["comment_prompt"] = body.comment_prompt.strip() or None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return out


class HookBody(BaseModel):
    text: str = ""
    background: str | None = None  # "" means back to the theme's palette


@app.post("/api/clip/{clip_id}/hook")
def rehook(clip_id: str, body: HookBody) -> dict[str, Any]:
    """A minute of ffmpeg, so it runs as a job like build does."""
    with db.connect() as conn:
        row = db.get(conn, clip_id)
        if row is None:
            raise HTTPException(404, f"no clip {clip_id}")
        ch = _resolve(conn, row["channel_id"])

    text = body.text.strip() or (row["hook_text"] or None)

    def work(emit) -> float:
        with db.connect() as conn:
            emit(f"{clip_id}  re-rendering with caption {text!r}"
                 + (f" and backdrop {body.background or 'from the theme'}" if body.background is not None else ""))
            outcome = pipeline.rehook(conn, clip_id, text, background=body.background)
            emit(f"{clip_id}  {outcome.status}: {outcome.detail}")
        return 0.0

    JOB.start("rehook", ch.id, work)
    return JOB.state()


@app.post("/api/clip/{clip_id}/reject")
def reject(clip_id: str, body: RejectBody) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.reject(conn, clip_id, body.reason)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": "qc_rejected"}


class MetricsBody(BaseModel):
    views: int
    avg_view_pct: float
    swipe_away_pct: float
    likes: int = 0


@app.post("/api/clip/{clip_id}/metrics")
def metrics(clip_id: str, body: MetricsBody) -> dict[str, str]:
    with db.connect() as conn:
        try:
            pipeline.set_metrics(
                conn,
                clip_id,
                views=body.views,
                avg_view_pct=body.avg_view_pct,
                swipe_away_pct=body.swipe_away_pct,
                likes=body.likes,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    return {"status": PUBLISHED}


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    settings.load().ensure_dirs()
    uvicorn.run(app, host=host, port=port, log_level="warning")
