from __future__ import annotations

import copy
import json
import os
import sqlite3
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# Where config.toml, prompts/, channels/, .env and data/ live. From a git
# checkout that is the checkout; from a pip install the package sits in
# site-packages and none of those are next to it, so FACTORY_ROOT names the
# directory instead — the Docker image sets it to /app.
ROOT = Path(os.environ.get("FACTORY_ROOT") or Path(__file__).resolve().parent.parent).resolve()

# What the Settings screen can change without anyone opening config.toml.
# config.toml stays the default; a value set on the page is an override in the
# database, shown as such, and removable. Paths are not here on purpose — the
# database's own location cannot come from the database.
SCHEMA: list[dict[str, Any]] = [
    {"section": "qc", "key": "max_sameness", "type": "number", "min": 0.5, "max": 1.0, "step": 0.01,
     "label": "Sameness ceiling", "help": "Perceptual similarity above this against any clip that could ship is a hard reject."},
    {"section": "qc", "key": "min_seconds", "type": "number", "min": 3, "max": 60, "step": 1,
     "label": "Shortest clip (s)", "help": "A finished race under this is refused before it costs anything."},
    {"section": "qc", "key": "max_seconds", "type": "number", "min": 10, "max": 180, "step": 1,
     "label": "Longest clip (s)"},
    {"section": "qc", "key": "target_lufs", "type": "number", "min": -24, "max": -8, "step": 0.5,
     "label": "Loudness target (LUFS)", "help": "-14 is what the platforms normalise to."},
    {"section": "qc", "key": "lufs_tolerance", "type": "number", "min": 0.5, "max": 8, "step": 0.5,
     "label": "Loudness tolerance (dB)"},
    {"section": "qc", "key": "min_hook_strength", "type": "number", "min": 1, "max": 5, "step": 1,
     "label": "Minimum QC hook score", "help": "The agent's 1-5 hook score; below this is a reject."},
    {"section": "overlay", "key": "seconds", "type": "number", "min": 0, "max": 10, "step": 0.1,
     "label": "Caption on screen (s)"},
    {"section": "overlay", "key": "marble_race", "type": "text", "label": "Opening captions",
     "help": "Two or three words that make the viewer pick a marble, separated by |; one is chosen per seed."},
    {"section": "publish", "key": "best_time", "type": "text", "label": "Upload time (local)",
     "help": "HH:MM in the timezone below. 06:00 Bangkok is US evening, the highest-CPM slot."},
    {"section": "publish", "key": "timezone", "type": "text", "label": "Your timezone",
     "help": "An IANA name such as Asia/Bangkok."},
    {"section": "notify", "key": "daily_at", "type": "text", "label": "Daily reminder (local time)",
     "help": "HH:MM; a Discord/Slack line with how many approved clips wait for upload. Empty disables."},
    {"section": "overlay", "key": "funnel_drop", "type": "text", "label": "Default funnel caption"},
    {"section": "overlay", "key": "ball_battle", "type": "text", "label": "Arena captions",
     "help": "For ball_battle, separated by |; one is chosen per seed."},
    {"section": "overlay", "key": "size", "type": "number", "min": 0.05, "max": 0.2, "step": 0.005,
     "label": "Caption size", "help": "As a fraction of the frame's width. Bigger is easier to read in the second a viewer gives it."},
    {"section": "overlay", "key": "cta", "type": "text", "label": "Closing ask",
     "help": "On screen after the winner crosses, e.g. COMMENT YOUR PICK. Empty turns it off."},
    {"section": "overlay", "key": "cta_seconds", "type": "number", "min": 0, "max": 5, "step": 0.1,
     "label": "Closing ask (s)"},
    {"section": "retention", "key": "rejected_days", "type": "number", "min": -1, "max": 365, "step": 1,
     "label": "Keep rejected files (days)", "help": "-1 keeps them forever. Only `factory gc` deletes."},
    {"section": "retention", "key": "published_days", "type": "number", "min": -1, "max": 3650, "step": 1,
     "label": "Keep published files (days)"},
    {"section": "render", "key": "fps", "type": "select", "options": [24, 30, 60], "label": "Frames per second"},
    {"section": "render", "key": "engine", "type": "select", "options": ["pil", "pygame"],
     "label": "Renderer", "help": "pygame draws motion on every object (squash, trails, sparks, glow); pil is the original look."},
    {"section": "render", "key": "render_scale", "type": "select", "options": [0.5, 1.0],
     "label": "Render scale", "help": "0.5 simulates at half size and upscales; 1.0 is sharper and about twice as slow."},
    {"section": "render", "key": "max_seconds", "type": "number", "min": 10, "max": 120, "step": 1,
     "label": "Simulation cap (s)"},
    {"section": "render", "key": "rounds", "type": "select", "options": [1, 2],
     "label": "Rounds per race clip", "help": "2 = a heat and a final with the same marbles on a different stage (about 30 s)."},
    {"section": "render", "key": "skip_start_s", "type": "number", "min": 0, "max": 3, "step": 0.1,
     "label": "Open mid-action (s dropped from the start)",
     "help": "The swipe decision is made in the first two seconds; marbles leaving the gate are the dullest part."},
    {"section": "analyst", "key": "min_published_for_rules", "type": "number", "min": 1, "max": 500, "step": 1,
     "label": "Clips before the Analyst may propose rules"},
]


def read_overrides(db_path: Path) -> dict[tuple[str, str], Any]:
    """Overrides from the database, or nothing if there is no database yet."""
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT section, key, value_json FROM settings").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    return {(s, k): json.loads(v) for s, k, v in rows}


def merged(base: dict, overrides: dict[tuple[str, str], Any]) -> dict:
    raw = copy.deepcopy(base)
    for (section, key), value in overrides.items():
        raw.setdefault(section, {})[key] = value
    return raw


@lru_cache(maxsize=1)
def load_env() -> int:
    """Read KEY=VALUE lines from .env into the environment, if it exists.

    A real environment variable always wins, so this can never quietly override
    a key you exported on purpose. The file is gitignored. It exists because an
    export in one terminal is invisible to every other process, which is a
    confusing way to lose half an hour.
    """
    path = ROOT / ".env"
    if not path.exists():
        return 0
    loaded = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


@dataclass(frozen=True)
class Settings:
    raw: dict
    base: dict = field(default_factory=dict)  # config.toml alone
    overrides: dict = field(default_factory=dict)  # (section, key) -> value

    @property
    def db_path(self) -> Path:
        return ROOT / self.raw["paths"]["db"]

    @property
    def work_dir(self) -> Path:
        return ROOT / self.raw["paths"]["work"]

    @property
    def out_dir(self) -> Path:
        return ROOT / self.raw["paths"]["out"]

    @property
    def channels_dir(self) -> Path:
        return ROOT / "channels"

    @property
    def rules_path(self) -> Path:
        """Legacy single-channel rules. Kept only as a seed for the first channel."""
        return ROOT / "rules.md"

    @property
    def render(self) -> dict:
        return self.raw["render"]

    @property
    def qc(self) -> dict:
        return self.raw["qc"]

    @property
    def llm(self) -> dict:
        return self.raw["llm"]

    def ensure_dirs(self) -> None:
        for path in (self.db_path.parent, self.work_dir, self.out_dir, self.channels_dir):
            path.mkdir(parents=True, exist_ok=True)


def from_root(root: Path) -> Settings:
    with open(root / "config.toml", "rb") as fh:
        base = tomllib.load(fh)
    overrides = read_overrides(root / base["paths"]["db"])
    return Settings(merged(base, overrides), base=base, overrides=overrides)


@lru_cache(maxsize=1)
def load() -> Settings:
    return from_root(ROOT)


def invalidate() -> None:
    """After an override changes. Tests replace `load`, so be tolerant of that."""
    getattr(load, "cache_clear", lambda: None)()
