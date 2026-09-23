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
  parked      marbles that end the clip not moving and not finished — but
              not one a holding trap has hold of, which is `held`, and judged
              over the race, not the tail; `short` counts races too brief to
              judge at all
  out         marbles outside the frame (a pinch that launched one)
  duration    the median finish, which gravity is tuned to
  lead        how often the leader changes — the drama

A stage passes when every gate below holds. `calibrate` tunes gravity so the
median finish lands mid-window; `run` measures; `report` writes the table
docs/06-stage-qa.md shows. The registry's weight is what makes a stage live,
and a stage is only given one after it passes here.

Parked and lead changes are measured over the *race* — up to the winner's
crossing — and everything else over the whole round. The split had to be made
explicit when POST_WIN_MAX_S went 2.8 -> 7.0 s: `stuck` reads two four-second
windows and `_leads` samples every frame, so given the round both were mostly
measuring the seven seconds after the result rather than the race.

What that was worth, measured on one tree over 48 seeds a stage, tail 2.8 vs
7.0 with the metrics over the round and then over the race:

  parked, round -> race   bumpers 85 -> 43 of 121, gauntlet 59 -> 41 of 133,
                          pinwheel 23 -> 12, trapdoor 22 -> 6, arcade 14 -> 7.
                          pinwheel and pachinko go from FAIL to pass on it.
  lead, round -> race     slightly *lower* everywhere: zigzag 6.2 -> 5.9,
                          switchback 1.8 -> 1.5. The round was counting the
                          runner-up joining the winner at the bottom of the
                          frame as the lead changing. Truer, and stricter.

One correction to what this file said before. The claim that five stages
(pegboard, switchback, orchard, carnival, labyrinth) went pass -> fail on the
tail change was wrong: it compared against a report generated before the
magnets and trapdoor sections changed the kit's geometry, so it charged the
tail for other people's changes. Like for like, four of those five already
failed at a 2.8 s tail, and only labyrinth moved — 1.6 -> 1.4 lead changes,
which the scoping does not put back because it is not the window artifact at
all: the longer tail clears the QC floor more often, so fewer seeds are
retried and first-attempt races get measured in place of retried ones. That
is the honest number for what ships.
"""

from __future__ import annotations

import contextlib
import math
import statistics
from dataclasses import dataclass, field
from typing import Iterator

from . import settings
from .generators import physics, stagekit

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
    # Races too short to judge for parking: `stuck` wants two PARKED_S windows
    # of race and the winner was home before it had them. Counted rather than
    # quietly skipped, because a parked figure drawn from half a stage's races
    # is weak evidence and the table should say so (pinwheel 21 of 48).
    unjudged: int = 0
    out: int = 0
    durations: list[float] = field(default_factory=list)
    # The gap winner -> second, per finished race, None when no second marble
    # ever crossed. With the shipping cut this can be no larger than
    # POST_WIN_MAX_S; `run(tail_s=...)` is how the uncut distribution behind
    # that constant gets measured.
    gaps: list[float | None] = field(default_factory=list)
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
        parked = f"{self.parked}/{self.others}"
        if self.unjudged:
            parked += f" ({self.unjudged} short)"
        return (f"| `{self.stage}` | {self.gravity:.0f} | {self.finished}/{self.seeds} | {self.first_try}/{self.seeds} | "
                f"{r['runner_up']:.0%} | {parked} | {self.out} | {self.median_s} | "
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
    """Lead changes, sampled twice a second; and which marbles were ever last.

    `states` is the race — up to and including the winner's crossing, not the
    whole round. After the winner is home the lead cannot change in any way a
    viewer would call a change: the winner sits at the bottom and stays lowest
    until the runner-up lands beside it, and *that* read as the lead changing.
    Scoping to the race takes those out, so the count goes down rather than up
    — zigzag 6.2 -> 5.9, switchback 1.8 -> 1.5 over 48 seeds. It makes this
    gate bite harder, not less, which is the right direction for a true
    number: five stages now sit under 1.5 (cascade 0.8, arcade 1.1, carnival
    1.3, labyrinth 1.4, trapdoor 1.4)."""
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


def stuck(states, i: int, style=None) -> bool:
    """Made no headway down the course in the last PARKED_S seconds of the race.

    First this was "moved under 20 px in two seconds", which is a marble at
    rest. It missed the one the agent's QA then found: wedged between a
    rocking plank and the wall, jiggled up and down by the plank for half a
    race, moving all the time and going nowhere. Headway is the lowest point
    reached, so a marble bouncing in place or pinched and shaken counts, and
    one queueing slowly through a funnel throat does not.

    `states` is the race, ending at the winner's crossing, because the two
    windows this reads are eight seconds long and the tail is now seven: given
    the round they would be almost entirely tail, and would report the state of
    the field after the result rather than a defect during the race. A marble
    going nowhere while the race is on is the defect this is for; one that was
    still working its way down and settled once the result was in is the normal
    end of a clip, which is what the render's `unfinished` reports separately.

    A race shorter than the two windows is not judged at all, and the windows
    are not shrunk to fit it. Scaling them down was tried and measured worse:
    early in a race a marble is still being let go from the top and covers
    little ground, so a 3 s window calls it parked when nothing is wrong —
    gauntlet went from 41 parked in 133 to 76, pinwheel 12 to 34, and plinko
    and pinball failed a gate they should pass. A false parked reading is the
    exact failure this scoping is meant to remove. The races that go unjudged
    are counted instead, as `Report.unjudged`, so the gap is visible rather
    than silent: 18% of races have a winner home inside 8 s.

    A marble sitting in a holding trap is the one exception, and it is not a
    looser threshold — see `held`."""
    window = int(PARKED_S * FPS)
    if len(states) < 2 * window:
        return False
    recent = min(s[i][1] for s in states[-window:])
    before = min(s[i][1] for s in states[-2 * window:-window])
    if before - recent >= PARKED_PX:
        return False
    return not held(states, i, style)


# How long a marble may be in a trap's pit before the pit stops explaining it.
# One period is one guaranteed opening: whatever the phase it landed on, the
# door has gone from under it once. A quarter more is the fall clear, which at
# gravity -30 is about 1.9 s against periods of 4.4-5.0 s. Taking the bound
# away entirely changes no verdict on the trapdoor stage (parked 7/60 over 24
# seeds and 12/117 over 48, either way), which is the point: it is the
# backstop for a marble wedged in a pit, not the thing deciding the everyday
# verdict. What decides that is being in a pit at all — without the
# distinction the same 48 seeds park 16 of 117 and the stage fails.
TRAP_HOLD_CYCLES = 1.25


def _in_pit(point, trap, big: float) -> bool:
    """Inside the pit's walls, between the door and the mouth."""
    x, y = point
    hx, hy, bore, depth, _period, _phase = trap
    return hx - big <= x <= hx + bore + big and hy - big <= y <= hy + depth


def held(states, i: int, style=None) -> bool:
    """In a trap's pit when the clip cut, and for less than the one cycle it
    takes the door to open underneath it.

    A held marble and a parked one look identical in the last eight seconds:
    both sit still and short of the line. What tells them apart is not how
    long they have been still but *what they are sitting on*. A trap's door
    runs on a clock that does not care what is on it (`stagekit.trap_angle`),
    so a marble in the pit is going to be let go, and when is arithmetic:
    inside one period, whatever phase it arrived on.

    That is also what still catches a genuinely stuck marble. Past
    TRAP_HOLD_CYCLES periods the floor has already swung away from under this
    one and it did not leave — it is wedged against a pit wall, not held —
    and it counts as parked again. Everywhere else on the course nothing
    changes: a stage with no trap takes the same path it always did.
    """
    traps = list(getattr(style, "traps", ()) or ())
    if not traps:
        return False
    big = W * stagekit.MARBLE_R
    here = next((t for t in traps if _in_pit(states[-1][i], t, big)), None)
    if here is None:
        return False
    inside = 0
    for state in reversed(states):
        if not _in_pit(state[i], here, big):
            break
        inside += 1
    return inside <= here[4] * TRAP_HOLD_CYCLES * FPS


def run(stage: str, seeds: range | list[int], *, gravity_value: float | None = None,
        tail_s: float | None = None, max_seconds: float | None = None,
        cut_on_runner_up: bool = True) -> Report:
    """Measure one stage over seeds.

    `tail_s` stands in for POST_WIN_MAX_S for this run only, which is how a
    candidate tail is costed before it is committed to.

    `cut_on_runner_up=False` also lifts POST_WIN_S, the shorter cut that fires
    once the second marble is home. That is only for measuring the uncut gap
    distribution: leave it on to cost a tail, because the runner-up cut is
    what keeps the median race from paying the whole tail. Measuring with it
    off put the cost of a 5.0 s tail at +1.8 s a round when it is +0.2 s.
    It needs `max_seconds` raised to match, or the race is truncated by the
    frame budget before a long gap can be seen.
    """
    cfg = settings.load().render
    params = {"stage": stage}
    if max_seconds is not None:
        params["max_seconds"] = max_seconds
    report = Report(stage=stage, gravity=gravity_value if gravity_value is not None else physics.STAGE_GRAVITY[stage])
    with gravity(stage, gravity_value):
        for seed in seeds:
            report.seeds += 1
            try:
                r = physics.run_round(seed, "marble_race", params, cfg, W, H, FPS,
                                      post_win_max_s=tail_s,
                                      post_win_s=None if cut_on_runner_up else tail_s)
            except RuntimeError as exc:
                report.failures.append(f"{seed}: {str(exc).split('(')[-1].rstrip(')')}")
                continue
            report.finished += 1
            report.first_try += r["attempts"] == 1
            report.runner_up += bool(r["runner_up"])
            report.gaps.append(r["margin_s"])
            report.durations.append(r["duration_s"])
            states, style = r["states"], r["style"]
            # Two of these are judged over the race and two over the round, and
            # the split is the point. Leaving the frame is a glitch whenever it
            # happens, and not having finished is only knowable at the cut, so
            # both read the round's last frame. Parking and the lead are
            # properties of the race, so they stop at the winner's crossing —
            # otherwise a seven-second tail is most of what they measure.
            race = states[: (r["winner_frame"] if r["winner_frame"] is not None
                             else len(states) - 1) + 1]
            if len(race) < 2 * int(PARKED_S * FPS):
                report.unjudged += 1
            last = states[-1]
            for i, (x, y) in enumerate(last):
                if not (-5 <= x <= W + 5 and -5 <= y <= H + 5):
                    report.out += 1
                    continue
                if y > 0.12 * H:  # above the line: did not finish
                    report.others += 1
                    if stuck(race, i, style):
                        report.parked += 1
            changes, ever_last = _leads(race)
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
        "Parked and lead changes are measured over the race — up to the winner's crossing — and the "
        "rest over the whole round. `(n short)` beside a parked figure is races whose winner was home "
        "before there was enough race to judge parking in; that figure is drawn from the rest.",
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
