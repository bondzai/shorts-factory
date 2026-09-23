"""The shared pipe. Every generator's output walks these stages in this order.

    plan -> render -> metadata -> qc -> (queue) -> approve -> publish -> metrics

Every stage is scoped to one channel: its rules, its allowed generators, its
publish driver, its credentials, its sameness history. Nothing crosses.

One module per stage, and each imports only from the stages before it:

    common -> spoilers -> planning, building -> words -> review -> publishing -> metrics

The names below are the pipe's public surface; the page, the command line and
an agent over MCP all call these and nothing deeper.
"""

from __future__ import annotations

from .building import Written, build, build_all, create_and_render, render_stage
from .common import StageOutcome, resolve, sample_times
from .metrics import digest, pull_metrics, set_metrics
from .planning import plan
from .publishing import publish_approved, publish_one
from .review import (
    STUCK,
    apply_qc,
    approve,
    bin_clips,
    destroy_clips,
    queue,
    reject,
    restore,
    resume,
    stuck,
    unbin_clips,
)
from .spoilers import RESULT_WORDS, lineup, spoiler, winners
from .words import attach_metadata, redescribe, rehook, retitle

__all__ = [
    "RESULT_WORDS", "STUCK", "StageOutcome", "Written", "apply_qc", "approve",
    "attach_metadata", "bin_clips", "build", "build_all", "create_and_render",
    "destroy_clips", "digest", "lineup", "plan", "publish_approved", "publish_one",
    "pull_metrics", "queue", "redescribe", "rehook", "reject", "render_stage",
    "resolve", "restore", "resume", "retitle", "sample_times", "set_metrics",
    "spoiler", "stuck", "unbin_clips", "winners",
]
