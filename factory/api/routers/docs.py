"""The documentation pages, and the reference generated from the code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ... import db
from ... import playbooks
from ... import settings
from ... import tasks
from ... import themes
from ...generators import physics
from ..common import resolve

router = APIRouter()

# factory/api/routers/ -> the checkout, where docs/ lives
DOCS = Path(__file__).resolve().parents[3] / "docs"


@router.get("/api/playbooks")
def list_playbooks() -> dict[str, Any]:
    return {"playbooks": playbooks.available()}


@router.get("/api/playbook/{name}")
def get_playbook(name: str, channel: str | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        ch = resolve(conn, channel)
    try:
        return {"name": name, "channel": ch.id, "text": playbooks.render(name, ch.id)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


def _reference() -> str:
    from ... import cli  # here: the other front end, imported only to list its
    # commands — the page must not depend on the command line to serve a request

    lines = ["# Reference", "", "Generated from the code at the moment you opened this page, so it cannot be stale.", ""]
    lines += ["## Settings the page can change", "", "| section | key | type | range | meaning |", "|---|---|---|---|---|"]
    for f in settings.SCHEMA:
        rng = f"{f['min']}–{f['max']}" if "min" in f else (", ".join(str(o) for o in f["options"]) if "options" in f else "")
        lines.append(f"| {f['section']} | `{f['key']}` | {f['type']} | {rng} | {f['label']}{' — ' + f['help'] if f.get('help') else ''} |")
    lines += ["", "## Task kinds", "", "| kind | meaning | parameters | built-in agents can do it |", "|---|---|---|---|"]
    for k, v in tasks.KINDS.items():
        lines.append(f"| `{k}` | {v['meaning']} | {', '.join(v['params']) or '—'} | {'yes' if v['builtin'] else 'no'} |")
    lines += ["", "## Stages", "", "| stage | what it is | built from | weight | gravity |", "|---|---|---|---|---|"]
    for st in physics.STAGE_SPECS:
        built = " → ".join(name for name, _ in st.parts) if st.parts else "hand-built"
        weight = f"{physics.STAGES[st.id]:.3f}" if st.live else "trial"
        lines.append(f"| `{st.id}` | {st.blurb} | {built} | {weight} | {st.gravity} |")
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


@router.get("/api/docs")
def list_docs() -> dict[str, Any]:
    pages = []
    for path in sorted(DOCS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = next((l[2:] for l in text.splitlines() if l.startswith("# ")), path.stem)
        pages.append({"id": path.stem, "title": title, "text": text})
    pages.append({"id": "reference", "title": "Reference", "text": _reference()})
    return {"pages": pages}
