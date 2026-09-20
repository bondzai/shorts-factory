"""Work as a queue, so the brain is interchangeable.

Put the instructions in the system once; whichever agent is around pulls the
next task and does it. An external agent (Codex, Claude Code) calls
`next_task` over MCP and gets the playbook for that kind of task with the
parameters filled in. `factory work` does the same with the built-in agents,
for the kinds they can do. Same table, same instructions, same results.
"""

from __future__ import annotations

import json
import random
import sqlite3
from typing import Any

from . import channels, db, logs, pipeline, playbooks

# kind -> what it means, which playbook explains it, what parameters it takes,
# and whether the built-in agents can do it without a person's judgement.
KINDS: dict[str, dict[str, Any]] = {
    "make-clip": {
        "meaning": "render one clip, look at it, title it, QC it",
        "playbook": "make-clip",
        "params": {"generator": "physics", "variant": "marble_race", "seed": None},
        "builtin": True,
    },
    "plan-week": {
        "meaning": "propose a week of clips from the numbers; nothing is rendered",
        "playbook": "plan-week",
        "params": {},
        "builtin": False,
    },
    "review": {
        "meaning": "judge what is waiting in the review queue",
        "playbook": "review",
        "params": {},
        "builtin": False,
    },
    "retitle": {
        "meaning": "propose new titles for published clips that underperform",
        "playbook": "retitle",
        "params": {},
        "builtin": False,
    },
}


def enqueue(
    conn: sqlite3.Connection, channel_id: str, kind: str, params: dict[str, Any] | None = None,
    *, count: int = 1, by: str = "human", priority: int = 0,
) -> list[int]:
    if kind not in KINDS:
        raise ValueError(f"no task kind {kind!r}; have {sorted(KINDS)}")
    if not 1 <= count <= 50:
        raise ValueError("count must be between 1 and 50")
    allowed = set(KINDS[kind]["params"])
    params = {k: v for k, v in (params or {}).items() if k in allowed and v not in (None, "")}
    if kind == "make-clip":
        ch = channels.get(conn, channel_id)
        generator = params.get("generator", "physics")
        variant = params.get("variant", "marble_race")
        if not ch.allows(generator, variant):
            raise ValueError(f"{channel_id} does not allow {generator}/{variant}; allowed: {ch.variants or 'any ready module'}")
        if count > 1 and "seed" in params:
            raise ValueError("a fixed seed makes one clip; drop the seed to make several")
    ids = [db.enqueue_task(conn, channel_id, kind, params, by=by, priority=priority) for _ in range(count)]
    logs.event("task.queued", channel=channel_id, kind=kind, count=count, params=params, by=by)
    return ids


def instructions(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    """The playbook for this kind, with this task's parameters on top."""
    params = json.loads(row["params_json"] or "{}")
    head = [f"# Task #{row['id']}: {row['kind']} on {row['channel_id']}", ""]
    if params:
        head.append("Parameters for this task — use exactly these:")
        head += [f"- {k}: {v}" for k, v in params.items()]
    else:
        head.append("This task has no parameters; the playbook below is the whole brief.")
    head += ["", f"When finished, call `finish_task` with task_id={row['id']}, ok=true and a one-line",
             "summary (and the clip_id if you made one). If it cannot be done, finish it with",
             "ok=false and say why — do not leave it claimed.", "", "---", ""]
    return "\n".join(head) + playbooks.render(KINDS[row["kind"]]["playbook"], row["channel_id"])


STEPS = {
    "make-clip": ["claimed", "rendered", "described", "qc", "finished"],
}
DEFAULT_STEPS = ["claimed", "finished"]


def steps(row: sqlite3.Row) -> list[dict[str, Any]]:
    """Where a task is, step by step, and who did each step.

    Nothing new is recorded for this: the claim is on the task row, the render,
    title and QC are events the clip already logs, the finish is the task row
    again. Derived on read, so it cannot disagree with the log.
    """
    names = STEPS.get(row["kind"], DEFAULT_STEPS)
    done: dict[str, dict[str, Any]] = {}
    if row["claimed_at"]:
        done["claimed"] = {"by": row["claimed_by"], "at": row["claimed_at"]}
    if row["clip_id"]:
        for e in reversed(logs.read(clip=row["clip_id"], limit=200)):
            if e["event"] == "clip.rendered":
                done.setdefault("rendered", {"by": e.get("by") or e.get("actor") or row["claimed_by"], "at": e["at"]})
            elif e["event"] == "clip.described":
                done.setdefault("described", {"by": e.get("by") or row["claimed_by"], "at": e["at"]})
            elif e["event"] == "clip.qc":
                done.setdefault("qc", {"by": e.get("by") or row["claimed_by"], "at": e["at"],
                                       "note": "passed" if e.get("passed") else "rejected"})
    if row["finished_at"]:
        done["finished"] = {"by": row["claimed_by"], "at": row["finished_at"], "note": row["status"]}
    out, current_seen = [], False
    for name in names:
        if name in done:
            out.append({"name": name, "state": "done", **done[name]})
        elif not current_seen and row["status"] == "claimed":
            out.append({"name": name, "state": "current", "by": row["claimed_by"]})
            current_seen = True
        else:
            out.append({"name": name, "state": "pending"})
    return out


def as_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "channel_id": row["channel_id"], "kind": row["kind"],
        "params": json.loads(row["params_json"] or "{}"), "status": row["status"],
        "priority": row["priority"], "created_at": row["created_at"], "created_by": row["created_by"],
        "claimed_at": row["claimed_at"], "claimed_by": row["claimed_by"], "finished_at": row["finished_at"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"], "clip_id": row["clip_id"],
        "meaning": KINDS.get(row["kind"], {}).get("meaning", ""),
        "steps": steps(row),
    }


def run_builtin(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Do one claimed task with the factory's own agents. Only for kinds marked builtin."""
    kind = row["kind"]
    if not KINDS.get(kind, {}).get("builtin"):
        raise ValueError(f"{kind} needs an external agent's judgement; the built-in worker does not take it")
    params = json.loads(row["params_json"] or "{}")
    if kind == "make-clip":
        used = {r["seed"] for r in conn.execute("SELECT seed FROM clips").fetchall()}
        seed = params.get("seed")
        rng = random.Random()
        while seed is None or seed in used:
            seed = rng.randrange(2**31 - 1)
        clip_id = db.insert_clip(
            conn, channel_id=row["channel_id"], generator=params.get("generator", "physics"),
            variant=params.get("variant", "marble_race"), seed=int(seed), params={},
            hook="", plan_why=f"task #{row['id']}",
        )
        outcome = pipeline.build(conn, clip_id)
        return {"clip_id": clip_id, "status": outcome.status, "detail": outcome.detail,
                "cost_usd": outcome.cost_usd}
    raise ValueError(f"no built-in handler for {kind}")


def work(
    conn: sqlite3.Connection, *, worker: str = "factory-work", channel_id: str | None = None,
    once: bool = False,
) -> list[dict[str, Any]]:
    """Pull tasks the built-in agents can do, until the queue has none left."""
    from . import llm

    if not llm.has_credentials():
        raise ValueError("the built-in agents are not ready (see `factory brains`); "
                         "an external agent can still work the queue over MCP")
    kinds = [k for k, spec in KINDS.items() if spec["builtin"]]
    done = []
    while True:
        row = db.claim_task(conn, worker, channel_id=channel_id, kinds=kinds)
        if row is None:
            break
        logs.event("task.claimed", channel=row["channel_id"], task=row["id"], kind=row["kind"], by=worker)
        try:
            result = run_builtin(conn, row)
            finished = db.finish_task(conn, row["id"], ok=True, result=result, clip_id=result.get("clip_id"))
        except Exception as exc:
            finished = db.finish_task(conn, row["id"], ok=False, error=str(exc))
        logs.event("task.finished", channel=row["channel_id"], task=row["id"], kind=row["kind"],
                   status=finished["status"], by=worker, error=finished["error"])
        done.append(as_dict(finished))
        if once:
            break
    return done
