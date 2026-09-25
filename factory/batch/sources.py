"""Where rows come from. One class per format; each yields plain dicts and
knows nothing about validation or the queue. A new format is a new class and
one line in SOURCES."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Protocol

import yaml


class JobSource(Protocol):
    name: str

    def read(self) -> Iterable[dict[str, Any]]: ...


class ListSource:
    """Rows already in memory: an agent's list over MCP, a console request."""

    def __init__(self, rows: list[dict[str, Any]], name: str = "list"):
        self.rows, self.name = rows, name

    def read(self) -> Iterable[dict[str, Any]]:
        yield from (dict(r) for r in self.rows)


def _jobs(data: Any, path: Path) -> list[dict[str, Any]]:
    if isinstance(data, dict) and "jobs" in data:
        data = data["jobs"]
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError(f"{path.name}: expected a list of jobs, or {{jobs: [...]}}")
    return data


class JsonSource:
    """A JSON array (or {"jobs": [...]}), or JSON Lines: one job per line."""

    def __init__(self, path: Path):
        self.path, self.name = path, path.name

    def read(self) -> Iterable[dict[str, Any]]:
        text = self.path.read_text()
        if self.path.suffix == ".jsonl":
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return _jobs(json.loads(text), self.path)


class YamlSource:
    def __init__(self, path: Path):
        self.path, self.name = path, path.name

    def read(self) -> Iterable[dict[str, Any]]:
        return _jobs(yaml.safe_load(self.path.read_text()), self.path)


class CsvSource:
    """One job per row. Empty cells are absent. `hint_title`, `hint_hook`,
    `hint_pin` and `hint_desc` become the hints; `params` may hold JSON."""

    HINTS = ("title", "hook", "pin", "desc")

    def __init__(self, path: Path):
        self.path, self.name = path, path.name

    def read(self) -> Iterable[dict[str, Any]]:
        with self.path.open(newline="") as fh:
            for raw in csv.DictReader(fh):
                row: dict[str, Any] = {k.strip(): v.strip() for k, v in raw.items()
                                       if k and v is not None and v.strip() != ""}
                hints = {h: row.pop(f"hint_{h}") for h in self.HINTS if f"hint_{h}" in row}
                if hints:
                    row["hints"] = hints
                if "params" in row:
                    row["params"] = json.loads(row["params"])
                yield row


SOURCES: dict[str, type] = {".csv": CsvSource, ".json": JsonSource, ".jsonl": JsonSource,
                            ".yaml": YamlSource, ".yml": YamlSource}


def source_for(path: Path) -> JobSource:
    try:
        return SOURCES[path.suffix.lower()](path)
    except KeyError:
        raise ValueError(f"{path.name}: no reader for {path.suffix or 'a file with no extension'}; "
                         f"have {', '.join(sorted(SOURCES))}") from None
