"""The generator the factory registers: variants in, a finished clip out.

A thin adapter. Everything it does lives in the modules beside it; this puts
the pieces in order for one clip and hands back what the pipeline measures.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Iterator

from ... import audio, settings
from ... import render as encoder
from ...series import story
from ...series.outcome import Outcome
from ..base import GeneratedClip
from . import outcome as physics_outcome
from . import replay
from .build import TRAITS
from .model import CLOSE_RACE_S, FINAL_CAPTION, Style, seconds
from .registry import LIVE_STAGES, STAGES
from .render import frames
from .simulate import run_round
from .text import closing_ask, default_hook, overlay, stage_text

VARIANTS = ["marble_race", "funnel_drop"]
MAX_ROUNDS = 3

# A clip cuts about a second after the runner-up crosses, so marbles still on
# their way down when it ends are the normal case, not a fault. Ten of the
# thirteen clips rendered on 2026-09-23 were rejected by the agent doing QC,
# most of them for "one of the three marbles never finishes" — which the
# facts, listing only who crossed, gave it no way to read any other way. So
# the render answers the question the agent was actually asking.
STOPPED_WINDOW_S = 2.0


def unfinished(round_: dict, fps: int) -> tuple[list[str], list[str]]:
    """Who had not crossed when the clip cut: the ones still racing, and the
    ones that had stopped.

    Still racing is measured the way stage QA measures a parked marble —
    headway, not speed, because a marble rattling in place between two pegs
    is moving and going nowhere. A marble that has covered less than its own
    radius in the last two seconds has stopped.
    """
    states, balls = round_["states"], round_["balls"]
    window = min(len(states) - 1, int(fps * STOPPED_WINDOW_S))
    running: list[str] = []
    stopped: list[str] = []
    gone = round_.get("gone") or {}
    for i, ball in enumerate(balls):
        if ball.name in round_["finish_s"] or ball.name in gone:
            continue
        (x0, y0), (x1, y1) = states[-1 - window][i], states[-1][i]
        moved = math.hypot(x1 - x0, y1 - y0)
        (running if moved > ball.radius else stopped).append(ball.name)
    return running, stopped


def screen_order(round_: dict) -> list[str]:
    """The marbles as the viewer meets them: left to right on the opening
    frame. The channel's rules name the colours in screen order and never the
    winner, so the order a title needs is this one — not the spawn order the
    balls list keeps, which on seed 470547365 read green, red, violet, blue,
    amber for a frame that showed red, blue, violet, amber, green."""
    first = round_["states"][0]
    return [b.name for _, b in sorted(zip(first, round_["balls"]), key=lambda t: t[0][0])]


def race_rounds(seed: int, variant: str, params: dict[str, Any], cfg: dict,
                sim_w: int, sim_h: int, fps: int) -> list[dict]:
    """Every round of one clip, simulated and not drawn.

    Up to MAX_ROUNDS. `round_params` (a list, one dict per round) is laid
    over `params` for that round: `stage` ("same" for the heat's), `mirror`,
    `friction` (x every static surface), `layout: k` (build round k's layout
    again, fresh marbles), or any section knob. Without it, round two is the
    final it always was."""
    rounds_wanted = int(params.get("rounds", cfg.get("rounds", 1))) if variant == "marble_race" else 1
    if rounds_wanted > MAX_ROUNDS:
        raise ValueError(f"rounds: {rounds_wanted}; a clip runs at most {MAX_ROUNDS}")
    per_round = list(params.get("round_params") or []) if variant == "marble_race" else []

    def over(n: int, base: dict, done: list[dict]) -> dict:
        extra = dict(per_round[n]) if n < len(per_round) and per_round[n] else {}
        if not extra:
            return base
        if extra.get("stage") == "same":
            extra["stage"] = done[0]["style"].stage
        if extra.get("layout") is not None:
            # Another round's layout: its stage, built from its seed's stream.
            src = done[int(extra.pop("layout"))]
            extra.setdefault("stage", src["style"].stage)
            extra["layout_seed"] = src["style"].seed
            extra["layout_picked"] = src.get("stage_picked", False)
        return {**base, **extra}

    rounds = [run_round(seed, variant, over(0, params, []), cfg, sim_w, sim_h, fps)]
    if rounds_wanted >= 2:
        # The final: same marbles, a different stage, a seed derived from
        # this one so the whole clip is still one number.
        heat = rounds[0]
        lineup = [(b.name, b.color) for b in heat["balls"]]
        other = [c for c in LIVE_STAGES if c != heat["style"].stage] or list(LIVE_STAGES)
        final_stage = params.get("final_stage") or random.Random(seed ^ 0x5F3759DF).choice(other)
        rounds.append(run_round(seed + 104729, variant, over(1, {**params, "stage": final_stage}, rounds),
                                  cfg, sim_w, sim_h, fps, lineup=lineup, round_index=1))
    if rounds_wanted >= 3:
        # A third round, the same way: a stage neither earlier round ran.
        lineup = [(b.name, b.color) for b in rounds[0]["balls"]]
        ran = {r["style"].stage for r in rounds}
        other = [c for c in LIVE_STAGES if c not in ran] or list(LIVE_STAGES)
        third = random.Random(seed ^ 0x2545F491).choice(other)
        rounds.append(run_round(seed + 2 * 104729, variant, over(2, {**params, "stage": third}, rounds),
                                cfg, sim_w, sim_h, fps, lineup=lineup, round_index=2))
    return rounds


def race_outcome(rounds: list[dict], fps: int, sim_w: int) -> Outcome:
    return physics_outcome.build(rounds, fps, sim_w, running=unfinished(rounds[-1], fps)[0])


# The story check's seeds: attempt k simulates seed + k * STORY_STRIDE, so
# attempt 0 is the task's own seed. Each attempt's clip also uses
# s + a * 7919 (stall retries, a < MAX_ATTEMPTS) and s + 104729 + a * 7919
# (the final's), s + 2 * 104729 + a * 7919 (a third round's). Those offsets
# are all under 250,000 in size and the stride is over a million, so no
# attempt can re-run another attempt's simulation.
STORY_STRIDE = 1_000_003


class StoryUnsatisfiable(RuntimeError):
    """No seed in the budget gave a race that meets the level's `must`."""


def story_seed(seed: int, attempt: int) -> int:
    return seed + attempt * STORY_STRIDE


def choose_story(seed: int, variant: str, params: dict[str, Any], cfg: dict,
                 sim_w: int, sim_h: int, fps: int) -> tuple[list[dict], Outcome, int, int]:
    """Simulate seeds until the story's `must` holds; return the best of the
    first `prefer_pool` passing races by `prefer` (earliest on a tie), its
    outcome, its seed, and how many seeds were simulated. Nothing is drawn:
    the caller renders only what this returns."""
    spec = params["story"] or {}
    must, prefer = spec.get("must") or {}, spec.get("prefer") or {}
    problems = story.validate(must) + story.validate(prefer)
    if problems:
        raise ValueError("story: " + "; ".join(problems))
    series = settings.load().raw.get("series", {})
    budget = int(params.get("max_story_attempts") or series.get("max_story_attempts", 200))
    pool = int(params.get("prefer_pool") or series.get("prefer_pool", 5))
    passing: list[tuple[float, int, int, list[dict], Outcome]] = []
    stalled = 0
    attempts = 0
    for k in range(budget):
        attempts = k + 1
        s = story_seed(seed, k)
        try:
            rounds = race_rounds(s, variant, params, cfg, sim_w, sim_h, fps)
        except RuntimeError:
            stalled += 1  # a seed that stalls on every retry is a story attempt spent
            continue
        outcome = race_outcome(rounds, fps, sim_w)
        if not story.failures(outcome, must):
            passing.append((story.score(outcome, prefer), -k, s, rounds, outcome))
            if len(passing) >= pool:
                break
    if not passing:
        raise StoryUnsatisfiable(
            f"story_unsatisfiable: must {must} not met by any of {attempts} attempts from seed {seed}"
            + (f" ({stalled} stalled)" if stalled else ""))
    _, _, s, rounds, outcome = max(passing, key=lambda p: (p[0], p[1]))
    return rounds, outcome, s, attempts


def generate(*, seed: int, variant: str, params: dict[str, Any], work_dir: Path) -> GeneratedClip:
    if variant not in VARIANTS:
        raise ValueError(f"physics: unknown variant {variant!r}")
    cfg = settings.load().render
    out_w, out_h = int(cfg["width"]), int(cfg["height"])
    scale = float(cfg["render_scale"])
    sim_w, sim_h = int(out_w * scale), int(out_h * scale)
    fps = int(cfg["fps"])

    outcome: Outcome | None = None
    rendered_seed, story_attempts = seed, 0
    if params.get("story"):
        if variant != "marble_race":
            raise ValueError(f"physics: a story needs a race, and {variant} is not one")
        rounds, outcome, rendered_seed, story_attempts = choose_story(seed, variant, params, cfg, sim_w, sim_h, fps)
    else:
        rounds = race_rounds(seed, variant, params, cfg, sim_w, sim_h, fps)
        if variant == "marble_race":
            outcome = race_outcome(rounds, fps, sim_w)

    clip_dir = work_dir
    clip_dir.mkdir(parents=True, exist_ok=True)

    # Captions: the heat states its measured stake; the final restates the
    # structure, never a result — the viewer just saw the heat, and naming
    # its winner again is one more word that is not a stake.
    hook_text = (params.get("hook_text") or "").strip() or default_hook(variant, rounds[0])
    overlays = [overlay(variant, sim_w, sim_h, fps, text=hook_text)]
    for n in range(1, len(rounds)):
        # The final's words are the clip's own (factory/captions); a middle
        # round of three is only a marker, and in words: captions carry no digits.
        caption = (params.get("final_text") or FINAL_CAPTION) if n == len(rounds) - 1 else "ROUND TWO"
        overlays.append(overlay(variant, sim_w, sim_h, fps, text=caption))
    # The closing ask's own words ride in the trace, so a redraw says the same.
    ask = closing_ask(sim_w, sim_h, fps, text=params.get("ask_text"))
    trace_path = replay.write(
        clip_dir, variant=variant, seed=rendered_seed, fps=fps, sim_w=sim_w, sim_h=sim_h, rounds=rounds,
        captions=[o[0] if o else None for o in overlays], ask=ask[0] if ask else None,
        outcome=outcome)

    impacts: list[audio.Impact] = []
    offset = 0.0
    for r in rounds:
        impacts += [audio.Impact(im.t + offset, im.strength, im.index, im.pan) for im in r["impacts"]]
        offset += r["duration_s"]
    duration_s = offset
    wav = audio.render_wav(impacts, duration_s, clip_dir / "audio.wav")

    def all_frames():
        for r, overlay in zip(rounds, overlays):
            yield from frames(r["states"], r["balls"], r["segments"], sim_w, sim_h,
                                    overlay=overlay, style=r["style"],
                                    ask=ask,
                                    winner_frame=r["winner_frame"], winner=r["winner"],
                                    impacts=r["impacts"], fps=fps)

    silent = encoder.encode_frames(
        all_frames(), out_path=clip_dir / "video.mp4",
        src_size=(sim_w, sim_h), out_size=(out_w, out_h), fps=fps,
    )
    final = encoder.mux(silent, wav, clip_dir / "clip.mp4")

    last = rounds[-1]
    balls, style = last["balls"], last["style"]
    if variant == "marble_race":
        names = ", ".join(b.name for b in rounds[0]["balls"])
        themed = "" if style.theme == "default" else f" Styled for {style.theme}."
        parts = []
        for i, r in enumerate(rounds):
            label = (("The heat" if i == 0 else "The final" if i == len(rounds) - 1 else f"Round {i + 1}")
                     if len(rounds) > 1 else f"{len(r['balls'])} marbles ({names}) race")
            if len(rounds) > 1:
                label += f" runs down {stage_text(r)}"
            else:
                label += f" down {stage_text(r)}"
            out = r.get("gone") or {}
            if out:
                # Elimination: say who was taken out, in the order it happened,
                # and whether the result came from the line or from survival.
                order = ", ".join(sorted(out, key=lambda n: (out[n], n)))
                parts.append(f"{label}; {len(out)} "
                             f"{'marble is' if len(out) == 1 else 'marbles are'} eliminated ({order}).")
                if r["winner"] and r.get("win_by") == "survival":
                    parts.append(f"The {r['winner']} marble is the last one left, at "
                                 f"{r['winner_frame'] / fps:.1f} seconds.")
                elif r["winner"]:
                    parts.append(f"The {r['winner']} marble reaches the bottom first, at "
                                 f"{r['winner_frame'] / fps:.1f} seconds.")
                else:
                    parts.append("No marble is left.")
                continue
            if r["winner"]:
                # When nobody else comes home, say how long was actually
                # watched, not POST_WIN_MAX_S. The two differ: a field that
                # comes to rest ends the round early, and so does the frame
                # budget, so the constant would claim a wait that was never
                # simulated. QC quotes this sentence back verbatim, so it has
                # to be a measurement rather than a setting.
                waited = r["duration_s"] - r["winner_frame"] / fps
                gap = (f", {seconds(r['margin_s'])} ahead of {r['runner_up']}" if r["runner_up"]
                       else f"; no other marble crosses in the next {waited:.1f} seconds")
                parts.append(f"{label}. The {r['winner']} marble reaches the bottom first, at "
                             f"{r['winner_frame'] / fps:.1f} seconds{gap}.")
            else:
                parts.append(f"{label}; none reaches the bottom within {r['duration_s']:.1f} seconds.")
        count_words = {2: "Two", 3: "Three"}
        head = (f"{count_words[len(rounds)]} rounds, same {len(rounds[0]['balls'])} marbles ({names}). "
                if len(rounds) > 1 else "")
        description = head + " ".join(parts) + themed
    else:
        description = (
            f"{len(balls)} small coloured balls pour through a narrow funnel throat "
            f"over {duration_s:.1f} seconds, clicking as they jam and release."
        )

    return GeneratedClip(
        video_path=final,
        duration_s=duration_s,
        description=description,
        facts={
            "variant": variant,
            "seed": seed,
            "rounds": [
                {"stage": r["style"].stage, "winner": r["winner"], "margin_s": r["margin_s"],
                 "runner_up": r["runner_up"], "finishes": r["finish_s"], "seconds": round(r["duration_s"], 2),
                 "obstacles": len(r["style"].circles) or len(r["segments"]), "spinners": len(r["style"].spinners),
                 "gate": bool(r["style"].gates),
                 "still_running_at_the_cut": unfinished(r, fps)[0],
                 "stopped_before_the_end": unfinished(r, fps)[1],
                 # Only a round with eliminations says so: a plain race's facts are unchanged.
                 **({"eliminated": sorted(r["gone"], key=lambda n: (r["gone"][n], n))} if r.get("gone") else {})}
                for r in rounds
            ],
            "winner": last["winner"],
            "impacts": len(impacts),
            "objects": len(balls),
            "ramps": len(last["segments"]),
            "stage": style.stage,
            "obstacles": len(style.circles) or len(last["segments"]),
            "theme": style.theme,
            "palette": style.background,
            "backdrop": "#%02x%02x%02x" % rounds[0]["style"].background,
            "sim_attempts": sum(r["attempts"] for r in rounds),
            "finishes": last["finish_s"],
            # Everyone who had not crossed when it cut, and which kind they
            # are: still on their way down, or stopped. Only the second is a
            # fault (see `unfinished`).
            "still_running_at_the_cut": unfinished(last, fps)[0],
            "stopped_before_the_end": unfinished(last, fps)[1],
            # For whoever writes the words: the colours in screen order, and
            # the stage in the render's own words with no result in them.
            "lineup": screen_order(rounds[0]) if variant == "marble_race" else [],
            "stage_words": stage_text(last) if variant == "marble_race" else "",
            "runner_up": last["runner_up"],
            "margin_s": last["margin_s"],
            "hook_text": hook_text,
            "outcome": outcome.model_dump(mode="json") if outcome is not None else None,
            # Seeds the story check simulated (0: the level had no story), and
            # the one it rendered; without a story that is `seed`.
            "story_attempts": story_attempts,
            "story_seed": rendered_seed,
            **({"cast": [e["id"] for e in params["cast"]]} if params.get("cast") else {}),
        },
        outcome=outcome,
        trace_path=trace_path,
    )


class PhysicsSandbox:
    """What `generators.register` wants: a name, the variants, and generate.

    Deliberately thin. The physics, the stages, the words and the drawing are
    modules beside this one; a generator is the socket they plug into.
    """

    name = "physics"
    variants = VARIANTS
    ready = True
    blurb = (
        "Deterministic 2D physics. marble_race: four coloured marbles race a "
        "zigzag ramp stage, one wins. funnel_drop: dozens of small balls pour "
        "through a funnel. No prior knowledge needed, holds attention to the end."
    )

    # Cast traits this generator acts on (docs/08, "Cast"); others are ignored.
    supported_traits = TRAITS

    def generate(self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path) -> GeneratedClip:
        return generate(seed=seed, variant=variant, params=params, work_dir=work_dir)

    def redraw(self, trace_dir: Path) -> Iterator[bytes]:
        """The frames the render encoded, at sim size, from a trace alone."""
        return replay.redraw(trace_dir)

    def redraw_frame(self, trace_dir: Path, round_index: int, frame: int) -> bytes:
        return replay.redraw_frame(trace_dir, round_index, frame)
