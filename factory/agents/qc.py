"""QC agent, and the hard checks around it.

QC has auto-reject authority. This is the decision that lets the pipeline grow
past about five clips a day: the approval queue you look at each morning holds
survivors only, so you approve by exception instead of inspecting everything.

Two layers:
  hard_failures()  arithmetic on ffprobe output and the perceptual hash. Cheap,
                   deterministic, and not the model's opinion.
  review()         the model looks at four frames and judges the hook.
Either layer can reject on its own.
"""

from __future__ import annotations

from typing import Any

from .. import llm, settings
from ..models import QCVerdict

SYSTEM = """You are the last check before a clip reaches a human review queue. \
You see four frames: the first moments, two middle points, and the end.

Judge two things only.

Hook: would a viewer who did not choose this clip keep watching past the first \
frame? Something must already be in motion, and whatever the clip asks the viewer \
to wait for must be legible immediately. Score 1 (nothing happens) to 5 (instantly \
gripping).

Templated: you are given short accounts of the previous clips on this channel. Set \
looks_templated to true if this clip would read to a viewer — or to a policy \
reviewer — as the same clip again with different numbers.

Be strict. Rejecting a mediocre clip costs one seed; publishing a run of \
interchangeable ones costs the channel's monetisation. Give your reasons as short \
factual statements."""


def hard_failures(
    *,
    probe: dict[str, Any],
    loudness_lufs: float | None,
    sameness: float,
) -> list[str]:
    cfg = settings.load().qc
    out: list[str] = []

    width, height = probe["width"], probe["height"]
    if height <= width:
        out.append(f"not vertical: {width}x{height}")
    elif abs(width / height - 9 / 16) > 0.01:
        out.append(f"aspect ratio is not 9:16: {width}x{height}")

    duration = probe["duration_s"]
    if duration < cfg["min_seconds"]:
        out.append(f"too short: {duration:.1f}s < {cfg['min_seconds']}s")
    if duration > cfg["max_seconds"]:
        out.append(f"too long: {duration:.1f}s > {cfg['max_seconds']}s")

    if loudness_lufs is None:
        out.append("no measurable audio track")
    else:
        target, tolerance = cfg["target_lufs"], cfg["lufs_tolerance"]
        if abs(loudness_lufs - target) > tolerance:
            out.append(
                f"loudness {loudness_lufs:.1f} LUFS is outside "
                f"{target} +/- {tolerance} LUFS"
            )

    if sameness > cfg["max_sameness"]:
        out.append(
            f"too similar to an existing clip: {sameness:.3f} > {cfg['max_sameness']}"
        )
    return out


def review(
    *, frames: list[bytes], hook: str, description: str, recent_descriptions: list[str]
) -> tuple[QCVerdict, float]:
    text = (
        f"Intended hook: {hook}\n"
        f"What happens: {description}\n\n"
        "Previous clips on this channel:\n"
        + (
            "\n".join(f"- {d}" for d in recent_descriptions)
            if recent_descriptions
            else "- none yet"
        )
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    content.extend(llm.image_blocks(frames))
    return llm.parse(QCVerdict, system=SYSTEM, content=content, max_tokens=4000, agent="qc")


def decide(verdict: QCVerdict, failures: list[str]) -> tuple[bool, str]:
    """Combine both layers. Returns (passed, reason-when-rejected)."""
    cfg = settings.load().qc
    reasons = list(failures)
    if verdict.verdict == "reject":
        reasons.extend(verdict.reasons)
    if verdict.hook_strength < cfg["min_hook_strength"]:
        reasons.append(
            f"hook_strength {verdict.hook_strength} < {cfg['min_hook_strength']}"
        )
    if verdict.looks_templated:
        reasons.append("reviewer read it as the same clip again")
    if verdict.policy_risk == "high":
        reasons.append("policy risk judged high")
    return (not reasons), "; ".join(reasons)
