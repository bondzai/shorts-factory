from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class GeneratedClip:
    """What a generator hands back to the shared pipe."""

    video_path: Path
    duration_s: float
    # Plain-language account of what actually happened in the render. The
    # Metadata agent writes the title from this, so it must be true.
    description: str
    facts: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Generator(Protocol):
    name: str
    variants: list[str]
    blurb: str  # shown to the Idea agent when it picks what to make
    ready: bool  # False keeps a half-built module out of the Idea agent's menu

    def generate(
        self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path
    ) -> GeneratedClip: ...


_REGISTRY: dict[str, Generator] = {}


def register(generator: Generator) -> Generator:
    if generator.name in _REGISTRY:
        raise ValueError(f"generator {generator.name!r} already registered")
    _REGISTRY[generator.name] = generator
    return generator


def get(name: str) -> Generator:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown generator {name!r}; have {sorted(_REGISTRY)}") from None


def all_generators() -> dict[str, Generator]:
    return dict(_REGISTRY)


def ready_generators() -> dict[str, Generator]:
    return {name: gen for name, gen in _REGISTRY.items() if getattr(gen, "ready", True)}


def available(allowed: list[str] | None = None) -> dict[str, list[str]]:
    """Ready generator -> its variants, narrowed to what a channel allows.

    `allowed` holds "generator/variant" strings; empty or None means the channel
    takes anything that is ready.
    """
    out: dict[str, list[str]] = {}
    for name, gen in ready_generators().items():
        variants = [
            v for v in gen.variants if not allowed or f"{name}/{v}" in allowed
        ]
        if variants:
            out[name] = variants
    return out


def catalogue(allowed: list[str] | None = None) -> str:
    """The generator menu, as text for the Idea agent's prompt. Ready modules only."""
    registry = ready_generators()
    return "\n".join(
        f"- {name} (variants: {', '.join(variants)}): {registry[name].blurb}"
        for name, variants in available(allowed).items()
    )
