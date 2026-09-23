"""The app itself: the door, the static files, and the routers behind them.

Binds to 127.0.0.1 by default. There is a password only when FACTORY_PASSWORD
is set: on this machine the page needs none, but the moment it is reachable
from elsewhere — a tablet over Tailscale, a VM on the internet — it needs a
door. One shared password, a signed cookie, no accounts: it is one operator's
console, not a product.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import notify, settings, telegram
from .. import workers as worker_service
from .common import STATIC
from .routers import (activity, channels, clips, config, docs, jobs, tasks, team, workers,
                      youtube)

app = FastAPI(title="shorts-factory", docs_url=None, redoc_url=None)



@app.on_event("startup")
def _start_daily_reminder() -> None:
    if not os.environ.get("FACTORY_NO_SCHEDULER"):
        notify.start_scheduler()
        telegram.start_polling()
        try:
            worker_service.MANAGER.restore()
            worker_service.MANAGER.start_loop_if_needed()
        except Exception:  # a worker that cannot come back must not stop the server
            pass


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


# The console is a Vite build in static/dist (source under web/). Its hashed
# assets are served from /assets, the page from /. The build is committed, so
# nothing at runtime needs node; `npm run build` in web/ refreshes it.
DIST = STATIC / "dist"


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    page = DIST / "index.html"
    if not page.exists():
        raise HTTPException(503, "the console is not built: run `npm install && npm run build` in web/")
    return page.read_text()


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn  # here: only `serve` needs it, and it is slow to import

    settings.load().ensure_dirs()
    uvicorn.run(app, host=host, port=port, log_level="warning")


for module in (channels, clips, tasks, jobs, config, docs, activity, team, workers, youtube):
    app.include_router(module.router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
