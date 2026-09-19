from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Pipeline states. A clip moves left to right; qc_rejected and failed are sinks.
PLANNED = "planned"
RENDERED = "rendered"
DESCRIBED = "described"
AWAITING_APPROVAL = "awaiting_approval"
QC_REJECTED = "qc_rejected"
APPROVED = "approved"
PUBLISHED = "published"
FAILED = "failed"


class ClipPlan(BaseModel):
    """What the Idea agent returns for one clip."""

    generator: str = Field(description="Name of a registered generator, exactly as given.")
    variant: str = Field(description="Variant name the generator supports.")
    seed: int = Field(ge=0, le=2**31 - 1)
    hook: str = Field(description="What the viewer sees in the first 1.5 seconds.")
    why: str = Field(description="One sentence: why this clip is worth making now.")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Generator-specific overrides. Leave empty unless a rule calls for one.",
    )


class ClipPlanBatch(BaseModel):
    plans: list[ClipPlan]


class Metadata(BaseModel):
    """English-language publishing metadata."""

    title: str = Field(min_length=20, max_length=90)
    description: str = Field(min_length=20, max_length=900)
    hashtags: list[str] = Field(min_length=3, max_length=5)
    rationale: str = Field(description="Why this title should stop a thumb.")


class QCVerdict(BaseModel):
    """What the QC agent thinks after looking at sampled frames."""

    verdict: Literal["pass", "reject"]
    hook_strength: int = Field(ge=1, le=5, description="1 = nothing happens, 5 = instantly gripping.")
    looks_templated: bool = Field(
        description=(
            "True only if this clip repeats THIS channel's own recent output — "
            "the same clip again with a new seed. Not whether the format is "
            "common elsewhere; a well-worn genre is fine."
        )
    )
    policy_risk: Literal["low", "medium", "high"]
    reasons: list[str] = Field(min_length=1, max_length=6)


class Finding(BaseModel):
    claim: str
    evidence: str = Field(description="The numbers this claim rests on.")
    n: int = Field(description="How many clips support it.")
    confidence: Literal["low", "medium", "high"]


class Digest(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    proposed_rules: list[str] = Field(
        default_factory=list,
        description="Markdown bullets to append to rules.md. Empty when n is too small.",
    )
