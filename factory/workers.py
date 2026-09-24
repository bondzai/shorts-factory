"""Workers: the console starts the agent, so nobody opens a terminal.

`bin/cowork` renders the work playbook and hands it to Claude Code or Codex
in the terminal you are sitting at. This does the same thing from the server:
one worker per channel, started and stopped from the Team screen, its output
kept in a log the page can show, and an **auto** mode that watches the queue
and starts the agent whenever there is something to do.

The agent runs non-interactively (`claude -p`, `codex exec`) with only the
factory's MCP tools pre-approved, exactly as `--unattended` does. It reads
the queue over MCP like any outside agent; nothing here bypasses the queue.

What lives where:

  process   one subprocess per channel, started on demand; stdout+stderr go
            to data/logs/workers/<channel>-<time>.log
  auto      a flag per channel, kept in the settings table so a restarted
            server picks the same workers up again
  loop      a daemon thread that, every few seconds, starts an auto worker
            whose channel has queued tasks and no process running

The agent binary has to be on the server's PATH. Inside the Docker image it
is not, and the page says so; there, `bin/cowork` on the host is the way.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, logs, playbooks, settings

PROMPT = "{prompt}"
MCP_JSON = "{mcp_json}"
# How each agent is run without a person at the keyboard. The prompt is the
# rendered work playbook; the tool allow-list is the factory's MCP server and
# nothing else, so a stuck agent waits rather than reaching for a shell.
# --strict-mcp-config with our own server spelled out means the agent loads
# only the factory: a worker's first run printed "several connectors need to
# be signed in: Gmail, Calendar, Drive…" because it had loaded every MCP
# server the operator's own Claude Code knows about, none of them wanted.
COMMANDS: dict[str, list[str]] = {
    "claude": ["claude", "-p", PROMPT, "--allowedTools", "mcp__shorts-factory", "--output-format", "text",
               "--strict-mcp-config", "--mcp-config", MCP_JSON],
    "codex": ["codex", "exec", "--full-auto", PROMPT],
}


def mcp_config_json() -> str:
    """The one MCP server a worker is allowed: this factory, from this venv."""
    import json

    factory = settings.ROOT / ".venv" / "bin" / "factory"
    return json.dumps({"mcpServers": {"shorts-factory": {"command": str(factory), "args": ["mcp"]}}})
POLL_S = 5.0
RESPAWN_BACKOFF_S = 20.0   # an agent that exits with work left waits this long before the next run
MAX_LOG_LINES = 400


def available() -> dict[str, bool]:
    return {name: shutil.which(cmd[0]) is not None for name, cmd in COMMANDS.items()}


def log_dir() -> Path:
    path = settings.load().db_path.parent / "logs" / "workers"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Worker:
    channel_id: str
    agent: str
    auto: bool = False
    process: subprocess.Popen | None = None
    log_path: Path | None = None
    started_at: str | None = None
    ended_at: str | None = None
    runs: int = 0
    last_exit: int | None = None
    last_error: str | None = None
    next_run_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def state(self) -> str:
        if self.running:
            return "running"
        if self.auto:
            return "waiting"
        return "stopped"

    def tail(self, lines: int = 12) -> list[str]:
        if not self.log_path or not self.log_path.exists():
            return []
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [ln for ln in text.splitlines() if ln.strip()][-lines:]

    def as_dict(self, tail: int = 4) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id, "agent": self.agent, "auto": self.auto, "state": self.state(),
            "pid": self.process.pid if self.running else None, "started_at": self.started_at,
            "ended_at": self.ended_at, "runs": self.runs, "last_exit": self.last_exit, "last_error": self.last_error,
            "log": str(self.log_path.name) if self.log_path else None, "tail": self.tail(tail),
        }


class Manager:
    def __init__(self) -> None:
        self.workers: dict[str, Worker] = {}
        self.lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # --- persistence ---------------------------------------------------------------

    def restore(self) -> None:
        """Bring back the auto flags a previous server had, and start them."""
        with db.connect() as conn:
            saved = {k[1]: v for k, v in db.overrides(conn).items() if k[0] == "workers"}
        for channel_id, spec in saved.items():
            if isinstance(spec, dict) and spec.get("auto"):
                self.workers[channel_id] = Worker(channel_id=channel_id, agent=spec.get("agent", "claude"), auto=True)

    def _save(self, worker: Worker) -> None:
        with db.connect() as conn:
            if worker.auto:
                db.set_override(conn, "workers", worker.channel_id, {"agent": worker.agent, "auto": True})
            else:
                db.clear_override(conn, "workers", worker.channel_id)
        # Logged either way: an auto flag that vanished between two server
        # restarts was not explained by anything in the code, and the log is
        # the only place that can say who turned it off.
        logs.event("worker.auto", channel=worker.channel_id, agent=worker.agent, auto=worker.auto)

    # --- control ---------------------------------------------------------------------

    def start(self, channel_id: str, agent: str = "claude", auto: bool = False) -> Worker:
        if agent not in COMMANDS:
            raise ValueError(f"no agent {agent!r}; have {sorted(COMMANDS)}")
        if not available().get(agent):
            raise ValueError(
                f"{agent} is not on the server's PATH. Install it where `factory serve` runs, "
                f"or run bin/cowork --channel {channel_id} --unattended on the host."
            )
        with self.lock:
            worker = self.workers.get(channel_id) or Worker(channel_id=channel_id, agent=agent)
            worker.agent, worker.auto = agent, auto
            self.workers[channel_id] = worker
        self._save(worker)
        if not worker.running:
            self._spawn(worker)
        self._ensure_loop()
        return worker

    def stop(self, channel_id: str) -> Worker | None:
        worker = self.workers.get(channel_id)
        if worker is None:
            return None
        worker.auto = False
        self._save(worker)
        if worker.running and worker.process is not None:
            worker.process.terminate()
            try:
                worker.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                worker.process.kill()
            self._reap(worker)
        return worker

    def status(self) -> list[dict[str, Any]]:
        for w in list(self.workers.values()):
            if w.process is not None and not w.running:
                self._reap(w)
        return [w.as_dict() for w in sorted(self.workers.values(), key=lambda w: w.channel_id)]

    def log(self, channel_id: str, lines: int = 120) -> list[str]:
        worker = self.workers.get(channel_id)
        return worker.tail(min(lines, MAX_LOG_LINES)) if worker else []

    # --- the process -----------------------------------------------------------------

    def _spawn(self, worker: Worker) -> None:
        with worker.lock:
            if worker.running:
                return
            prompt = playbooks.render("work", worker.channel_id)
            fill = {PROMPT: prompt, MCP_JSON: mcp_config_json()}
            cmd = [fill.get(part, part) for part in COMMANDS[worker.agent]]
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            worker.log_path = log_dir() / f"{worker.channel_id}-{stamp}.log"
            handle = open(worker.log_path, "ab")
            env = {**os.environ, "FACTORY_ACTOR": "worker"}
            try:
                worker.process = subprocess.Popen(
                    cmd, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    cwd=str(settings.ROOT), env=env,
                )
            except OSError as exc:
                handle.close()
                worker.last_error = str(exc)
                logs.event("worker.failed", level="error", channel=worker.channel_id, agent=worker.agent, error=str(exc))
                raise ValueError(f"could not start {worker.agent}: {exc}") from None
            worker.started_at = db.now()
            worker.ended_at = None
            worker.last_error = None
            worker.runs += 1
        logs.event("worker.started", channel=worker.channel_id, agent=worker.agent, pid=worker.process.pid, run=worker.runs)

    def _reap(self, worker: Worker) -> None:
        if worker.process is None:
            return
        code = worker.process.poll()
        if code is None:
            return
        worker.last_exit = code
        worker.ended_at = db.now()
        worker.process = None
        worker.next_run_at = time.time() + RESPAWN_BACKOFF_S
        logs.event("worker.exited", level="warn" if code else "info", channel=worker.channel_id,
                   agent=worker.agent, code=code, run=worker.runs)

    # --- auto ------------------------------------------------------------------------

    def _queued(self, channel_id: str) -> int:
        with db.connect() as conn:
            return db.task_counts(conn, channel_id).get("queued", 0)

    def tick(self) -> None:
        """One pass: reap finished processes, start auto workers with work waiting."""
        for worker in list(self.workers.values()):
            if worker.process is not None and not worker.running:
                self._reap(worker)
            if worker.auto and not worker.running and time.time() >= worker.next_run_at:
                try:
                    if self._queued(worker.channel_id) > 0:
                        self._spawn(worker)
                except Exception as exc:  # a bad spawn must not stop the loop
                    worker.last_error = str(exc)
                    worker.next_run_at = time.time() + RESPAWN_BACKOFF_S * 3

    def _ensure_loop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        def loop() -> None:
            while True:
                try:
                    self.tick()
                except Exception:
                    pass
                time.sleep(POLL_S)

        self._thread = threading.Thread(target=loop, name="workers", daemon=True)
        self._thread.start()

    def start_loop_if_needed(self) -> None:
        if any(w.auto for w in self.workers.values()):
            self._ensure_loop()


MANAGER = Manager()


# --- for an agent that is not ours to run ----------------------------------------------

def integration(channel_id: str) -> dict[str, Any]:
    """Everything an outside agent needs, ready to copy."""
    factory = settings.ROOT / ".venv" / "bin" / "factory"
    server = {"command": str(factory), "args": ["mcp"]}
    return {
        "claude_code": f"claude mcp add --scope user shorts-factory -- {factory} mcp",
        "mcp_json": {"mcpServers": {"shorts-factory": server}},
        "codex_toml": (
            "[mcp_servers.shorts-factory]\n"
            f"command = \"{factory}\"\n"
            "args = [\"mcp\"]\n"
        ),
        "cowork": f"bin/cowork --channel {channel_id} --unattended",
        "prompt_command": f"{factory} playbook work --channel {channel_id}",
        "tools_note": "The agent needs only the shorts-factory MCP tools; the prompt is `factory playbook work`.",
    }
