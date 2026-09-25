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
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import notify, settings, telegram
from .. import workers as worker_service
from .common import STATIC
from .routers import (activity, channels, clips, config, docs, feedback, jobs, season, tasks, team,
                      workers, youtube)

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


def _secrets() -> list[str]:
    """What opens the door: the password, a PIN (FACTORY_PIN, for a tablet's
    number pad), or both. Either one signs you in."""
    settings.load_env()
    return [v for v in (os.environ.get("FACTORY_PASSWORD"), os.environ.get("FACTORY_PIN")) if v]


def _password() -> str | None:
    """The secret the session cookie is signed with; None: no door at all."""
    found = _secrets()
    return found[0] if found else None


# A four-digit PIN has ten thousand values, so wrong guesses are rationed per
# address: five, then a minute's wait. Kept in memory; a restart forgives.
MAX_FAILS, LOCK_S = 5, 60.0
_FAILS: dict[str, tuple[int, float]] = {}


def _locked(addr: str) -> bool:
    fails, until = _FAILS.get(addr, (0, 0.0))
    return fails >= MAX_FAILS and time.monotonic() < until


def _failed(addr: str) -> None:
    fails, until = _FAILS.get(addr, (0, 0.0))
    if fails >= MAX_FAILS and time.monotonic() >= until:
        fails = 0
    fails += 1
    _FAILS[addr] = (fails, time.monotonic() + LOCK_S if fails >= MAX_FAILS else 0.0)


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


PIN_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,maximum-scale=1">
<link rel=icon type=image/svg+xml href=/static/logo.svg><title>shorts factory</title><style>
body{margin:0;background:#0d1117;color:#e6edf3;font:18px system-ui;display:grid;place-items:center;min-height:100vh;-webkit-user-select:none;user-select:none}
@media(prefers-color-scheme:light){body{background:#f6f8fa;color:#1f2328}}
main{display:grid;gap:22px;justify-items:center;width:min(340px,92vw)}b{display:flex;align-items:center;gap:10px;font-size:20px}b img{width:30px;height:30px}
p{margin:0;color:#9198a1;min-height:1.4em;text-align:center}.dots{display:flex;gap:16px}.dots i{width:16px;height:16px;border-radius:50%;border:2px solid #3d444d}
.dots i.on{background:#4493f8;border-color:#4493f8}.pad{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;width:100%}
.pad button{font:600 26px system-ui;height:74px;border-radius:18px;border:1px solid #30363d;background:#151b23;color:inherit;touch-action:manipulation}
@media(prefers-color-scheme:light){.pad button{background:#fff;border-color:#d1d9e0}}.pad button:active{background:#4493f8;color:#fff}
.pad .ghost{background:transparent;border:0;font-size:18px;color:#9198a1}form{display:none}a{color:#9198a1;font-size:14px}</style>
<main><b><img src=/static/logo.svg alt="">shorts factory</b><p id=msg>{MSG}</p><div class=dots id=dots></div>
<div class=pad id=pad></div><a href=/login?password=1>Use the password instead</a></main>
<form method=post action=/login id=f><input name=password id=pw></form>
<script>
const n={N},dots=document.getElementById("dots"),pad=document.getElementById("pad"),pw=document.getElementById("pw");let v="";
for(let i=0;i<n;i++)dots.appendChild(document.createElement("i"));
const show=()=>[...dots.children].forEach((d,i)=>d.classList.toggle("on",i<v.length));
const press=k=>{if(k==="del")v=v.slice(0,-1);else if(v.length<n)v+=k;show();if(v.length===n){pw.value=v;document.getElementById("f").submit();}};
["1","2","3","4","5","6","7","8","9","","0","del"].forEach(k=>{const b=document.createElement("button");b.type="button";
b.textContent=k==="del"?"Delete":k;if(!k){b.disabled=true;b.className="ghost";b.textContent="";}else if(k==="del")b.className="ghost";b.onclick=()=>press(k);pad.appendChild(b);});
document.addEventListener("keydown",e=>{if(/^[0-9]$/.test(e.key))press(e.key);else if(e.key==="Backspace")press("del");});
</script>"""


def _login_page(message: str, request: Request | None = None, status: int = 200) -> HTMLResponse:
    settings.load_env()
    pin = os.environ.get("FACTORY_PIN")
    wants_password = request is not None and request.query_params.get("password")
    if pin and pin.isdigit() and not wants_password:
        return HTMLResponse(PIN_PAGE.replace("{MSG}", message).replace("{N}", str(len(pin))), status_code=status)
    return HTMLResponse(LOGIN_PAGE % message, status_code=status)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return _login_page("Enter your PIN" if os.environ.get("FACTORY_PIN") else
                       "One password, set as FACTORY_PASSWORD where the server runs.", request)


@app.post("/login")
async def login(request: Request):
    addr = request.client.host if request.client else "?"
    if _locked(addr):
        return _login_page("Too many tries. Wait a minute.", status=429)
    form = await request.form()
    given = str(form.get("password", ""))
    known = _secrets()
    if known and any(secrets.compare_digest(given, s) for s in known):
        _FAILS.pop(addr, None)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, _token(known[0]), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 90)
        return response
    _failed(addr)
    return _login_page("That is not it." if not _locked(addr) else "Too many tries. Wait a minute.",
                       status=401 if not _locked(addr) else 429)


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


for module in (channels, clips, tasks, jobs, config, docs, activity, team, workers, youtube, season, feedback):
    app.include_router(module.router)

app.mount("/static", StaticFiles(directory=STATIC), name="static")
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
