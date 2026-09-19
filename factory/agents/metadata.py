"""Metadata agent: English title, description and hashtags.

It is shown frames from the finished render, not just the plan, because a title
that promises something the clip does not show is the fastest way to a bad
retention number.
"""

from __future__ import annotations

import json
from typing import Any

from .. import llm
from ..models import Metadata

SYSTEM = """You write publishing metadata in English for short vertical videos \
with no narration, aimed at a worldwide audience (largest markets: US, UK, \
Germany, Brazil, India).

You are shown the frames of the finished clip and a factual account of what \
happens in it. Write a title that makes someone stop scrolling and that the clip \
actually delivers. Never promise anything not visible in the frames.

Write like a native speaker: plain words, no marketing register, no stacked \
punctuation, no ALL CAPS, no emoji. The title, description and every hashtag must \
be English only — no Thai characters anywhere. Obey the rules file exactly."""


def write_metadata(
    *,
    description: str,
    facts: dict[str, Any],
    hook: str,
    rules: str,
    recent_titles: list[str],
    frames: list[bytes],
) -> tuple[Metadata, float]:
    text = (
        f"rules.md:\n---\n{rules}\n---\n\n"
        f"What happens in the clip: {description}\n"
        f"Generator facts: {json.dumps(facts, default=str)}\n"
        f"Intended hook: {hook}\n\n"
        "Titles already used on this channel (do not repeat their shape):\n"
        + ("\n".join(f"- {t}" for t in recent_titles) if recent_titles else "- none yet")
        + "\n\nThe attached frames are sampled from the start, two middle points, "
        "and the end of the clip."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    content.extend(llm.image_blocks(frames))

    metadata, cost = llm.parse(Metadata, system=SYSTEM, content=content, max_tokens=4000, agent="metadata")
    return metadata, cost
