"""Stage QA: a stage ships when the numbers say it races, not when it looks right.

Every lesson in docs/04 was a stage that looked fine in a still and failed
in the solver: marbles wedged in a sieve, pinched against a gauntlet wall,
parked beside a rocker, flung out of the frame. This runs a stage over many
seeds, through the same retry loop a real render uses, and measures what a
viewer would notice:

  finish      the race ends with a winner, inside the QC window
  first try   it did so on the seed's first attempt (retries are a cost)
  runner-up   a second marble crosses before the clip cuts — the payoff
              for everyone who backed a different colour
  parked      marbles that end the clip not moving and not finished
  out         marbles outside the frame (a pinch that launched one)
  duration    the median finish, which gravity is tuned to
  lead        how often the leader changes — the drama

A stage passes when every gate below holds. `calibrate` tunes gravity so the
median finish lands mid-window; `run` measures; `report` writes the table
docs/06-stage-qa.md shows. The registry's weight is what makes a stage live,
and a stage is only given one after it passes here.
"""

from __future__ import annotations

import contextlib
import math
import statistics
from dataclasses import dataclass, field
from typing import Iterator

from . import settings
from .generators import physics

W, H, FPS = 540, 960, 30

# The gates. Each is a line a stage has been seen to cross the wrong way.
GATES = {
    "finish_rate": 0.95,    # at most one seed in twenty fails every attempt
    # Half the seeds right first time. A seed under the floor is retried on a
    # seed derived from it, which the viewer never sees; the old drums stage
    # ships at 3 in 12 first try. Set at 0.6 first, before that was measured.
    "first_try": 0.50,
    "runner_up": 0.40,      # four in ten races show the second marble arrive
    "parked_max": 0.12,     # of the marbles that did not finish
    "out_max": 0,           # none, ever
    # Median finish, seconds after the opening skip. The floor was 12.0 until
    # the stages the channel already ships were measured: drums 10.9, sieve
    # 12.5, pinwheel 12.7. Below 11.5 most seeds need a retry.
    "duration": (11.5, 18.0),
    "lead_changes": 1.5,    # mean per race
}
TARGET_S = 14.0
# The least gravity calibration may use, as a magnitude. Below about this a
# stage looks like the moon: round two of QA tuned three stages to -13..-22
# to stretch them to 15 s, and a marble drifting through bumpers reads as a
# bug, not a race. A stage too quick at this gravity needs more in its way.
G_MIN = 30.0
PARKED_PX = 25.0  # got less than this much further down the course ...
PARKED_S = 4.0    # ... in each of the last two windows of this many seconds


@dataclass
class Report:
    stage: str
    gravity: float
    seeds: int = 0
    finished: int = 0
    first_try: int = 0
    runner_up: int = 0
    parked: int = 0
    others: int = 0
    out: int = 0
    durations: list[float] = field(default_factory=list)
    leads: list[int] = field(default_factory=list)
    comebacks: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def median_s(self) -> float | None:
        return round(statistics.median(self.durations), 1) if self.durations else None

    @property
    def rates(self) -> dict[str, float]:
        n = max(self.seeds, 1)
        done = max(self.finished, 1)
        return {
            "finish_rate": self.finished / n,
            "first_try": self.first_try / n,
            "runner_up": self.runner_up / done,
            "parked": self.parked / max(self.others, 1),
            "lead_changes": statistics.mean(self.leads) if self.leads else 0.0,
            "comeback": self.comebacks / done,
        }

    def problems(self) -> list[str]:
        r, g = self.rates, GATES
        out = []
        if r["finish_rate"] < g["finish_rate"]:
            out.append(f"finishes {self.finished}/{self.seeds}")
        if r["first_try"] < g["first_try"]:
            out.append(f"first try {self.first_try}/{self.seeds}")
        if r["runner_up"] < g["runner_up"]:
            out.append(f"runner-up {self.runner_up}/{self.finished}")
        if r["parked"] > g["parked_max"]:
            out.append(f"parked {self.parked}/{self.others}")
        if self.out > g["out_max"]:
            out.append(f"{self.out} out of frame")
        lo, hi = g["duration"]
        if self.median_s is None or not lo <= self.median_s <= hi:
            out.append(f"median {self.median_s}s")
        if r["lead_changes"] < g["lead_changes"]:
            out.append(f"lead changes {r['lead_changes']:.1f}")
        return out

    @property
    def passed(self) -> bool:
        return not self.problems()

    def row(self) -> str:
        r = self.rates
        verdict = "pass" if self.passed else "FAIL: " + "; ".join(self.problems())
        return (f"| `{self.stage}` | {self.gravity:.0f} | {self.finished}/{self.seeds} | {self.first_try}/{self.seeds} | "
                f"{r['runner_up']:.0%} | {self.parked}/{self.others} | {self.out} | {self.median_s} | "
                f"{r['lead_changes']:.1f} | {r['comeback']:.0%} | {verdict} |")


@contextlib.contextmanager
def gravity(stage: str, value: float | None) -> Iterator[None]:
    """Run with a different gravity for one stage, then put it back."""
    if value is None:
        yield
        return
    before = physics.STAGE_GRAVITY[stage]
    physics.STAGE_GRAVITY[stage] = value
    try:
        yield
    finally:
        physics.STAGE_GRAVITY[stage] = before


def _leads(states) -> tuple[int, int | None]:
    """Lead changes, sampled twice a second; and which marbles were ever last."""
    leader, changes, last_seen = None, 0, set()
    for frame in range(0, len(states), 15):
        ys = [y for _, y in states[frame]]
        now = min(range(len(ys)), key=lambda i: ys[i])
        if leader is not None and now != leader:
            changes += 1
        leader = now
        if frame >= 2 * FPS:
            last_seen.add(max(range(len(ys)), key=lambda i: ys[i]))
    return changes, last_seen


def stuck(states, i: int) -> bool:
    """Made no headway down the course in the last PARKED_S seconds.

    First this was "moved under 20 px in two seconds", which is a marble at
    rest. It missed the one the agent's QA then found: wedged between a
    rocking plank and the wall, jiggled up and down by the plank for half a
    race, moving all the time and going nowhere. Headway is the lowest point
    reached, so a marble bouncing in place or pinched and shaken counts, and
    one queueing slowly through a funnel throat does not."""
    window = int(PARKED_S * FPS)
    if len(states) < 2 * window:
        return False
    recent = min(s[i][1] for s in states[-window:])
    before = min(s[i][1] for s in states[-2 * window:-window])
    return before - recent < PARKED_PX


def run(stage: str, seeds: range | list[int], *, gravity_value: float | None = None) -> Report:
    cfg = settings.load().render
    report = Report(stage=stage, gravity=gravity_value if gravity_value is not None else physics.STAGE_GRAVITY[stage])
    gen = physics.PhysicsSandbox()
    with gravity(stage, gravity_value):
        for seed in seeds:
            report.seeds += 1
            try:
                r = gen._round(seed, "marble_race", {"stage": stage}, cfg, W, H, FPS)
            except RuntimeError as exc:
                report.failures.append(f"{seed}: {str(exc).split('(')[-1].rstrip(')')}")
                continue
            report.finished += 1
            report.first_try += r["attempts"] == 1
            report.runner_up += bool(r["runner_up"])
            report.durations.append(r["duration_s"])
            states = r["states"]
            last = states[-1]
            for i, (x, y) in enumerate(last):
                if not (-5 <= x <= W + 5 and -5 <= y <= H + 5):
                    report.out += 1
                    continue
                if y > 0.12 * H:  # above the line: did not finish
                    report.others += 1
                    if stuck(states, i):
                        report.parked += 1
            changes, ever_last = _leads(states)
            report.leads.append(changes)
            winner_index = next((i for i, b in enumerate(r["balls"]) if b.name == r["winner"]), None)
            report.comebacks += winner_index in ever_last
    return report


def calibrate(stage: str, seeds, *, start: float | None = None, rounds: int = 5, log=print) -> float:
    """Gravity that puts the median finish near TARGET_S. Finish time goes
    roughly as 1/sqrt(g) in free fall and closer to 1/g on a slow stage, so
    step by the square of the error and damp it; five rounds is plenty."""
    g = start if start is not None else physics.STAGE_GRAVITY[stage]
    lo, hi = GATES["duration"]
    for i in range(rounds):
        rep = run(stage, seeds, gravity_value=g)
        med = rep.median_s
        log(f"  {stage} g={g:.0f}: median {med}s, finished {rep.finished}/{rep.seeds}")
        if med is None:
            g *= 1.6  # nothing finished: speed it up
            continue
        if TARGET_S - 1.0 <= med <= TARGET_S + 1.5:
            break
        factor = max(0.45, min(2.2, (med / TARGET_S) ** 1.6))
        g *= factor
        if abs(g) < G_MIN:
            g = -G_MIN if g < 0 else G_MIN
            if abs(rep.gravity) <= G_MIN:
                break  # already at the floor: geometry, not gravity, has to change
    return round(g, 0)


def report_markdown(reports: list[Report], seeds: int) -> str:
    g = GATES
    head = [
        "# Stage QA",
        "",
        f"Every stage run over {seeds} seeds through the same retry loop a render uses. "
        "Generated by `factory stage-qa --report`; do not edit by hand.",
        "",
        "A stage passes when: it finishes on at least "
        f"{g['finish_rate']:.0%} of seeds and first try on {g['first_try']:.0%}; a runner-up crosses in "
        f"{g['runner_up']:.0%} of races; no more than {g['parked_max']:.0%} of unfinished marbles are parked "
        f"and none leave the frame; the median finish is {g['duration'][0]}-{g['duration'][1]:.0f} s; and "
        f"the lead changes {g['lead_changes']} times a race or more.",
        "",
        "A stage built from sections is given a weight — picked at random — only after it passes. "
        "The eleven hand-built stages predate QA and keep the weights they had; their verdicts are "
        "here so that can be decided on numbers. A stage with weight 0 (trial) still races when a task names it.",
        "",
        "| stage | built from | status | gravity | finished | first try | runner-up | parked | out | median s | lead changes | comeback | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    rows = []
    for r in reports:
        spec = physics.STAGE_BY_ID.get(r.stage)
        built = " → ".join(name for name, _ in spec.parts) if spec and spec.parts else "hand-built"
        status = f"live {physics.STAGES.get(r.stage, 0):.0%}" if spec and spec.live else "trial"
        rows.append(r.row().replace(f"| `{r.stage}` |", f"| `{r.stage}` | {built} | {status} |", 1))
    return "\n".join(head + rows) + "\n"
