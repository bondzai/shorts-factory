from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


@lru_cache(maxsize=1)
def load() -> Settings:
    with open(ROOT / "config.toml", "rb") as fh:
        return Settings(tomllib.load(fh))
