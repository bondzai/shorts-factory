from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    def rules_path(self) -> Path:
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
        for path in (self.db_path.parent, self.work_dir, self.out_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def load() -> Settings:
    with open(ROOT / "config.toml", "rb") as fh:
        return Settings(tomllib.load(fh))
