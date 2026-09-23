"""The generator the factory registers: variants in, a finished clip out.

A thin adapter. Everything it does lives in the modules beside it; this puts
the pieces in order for one clip and hands back what the pipeline measures.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from ... import audio, settings
from ... import render as encoder
from ..base import GeneratedClip
from .model import CLOSE_RACE_S, FINAL_CAPTION, POST_WIN_MAX_S, Style, seconds
from .registry import LIVE_STAGES, STAGES
from .render import frames
from .simulate import run_round
from .text import closing_ask, default_hook, overlay, stage_text

VARIANTS = ["marble_race", "funnel_drop"]

def generate(*, seed: int, variant: str, params: dict[str, Any], work_dir: Path) -> GeneratedClip:
    if variant not in VARIANTS:
        raise ValueError(f"physics: unknown variant {variant!r}")
    cfg = settings.load().render
    out_w, out_h = int(cfg["width"]), int(cfg["height"])
    scale = float(cfg["render_scale"])
    sim_w, sim_h = int(out_w * scale), int(out_h * scale)
    fps = int(cfg["fps"])

    rounds_wanted = int(params.get("rounds", cfg.get("rounds", 1))) if variant == "marble_race" else 1
    rounds = [run_round(seed, variant, params, cfg, sim_w, sim_h, fps)]
    if rounds_wanted >= 2:
        # The final: same marbles, a different stage, a seed derived from
        # this one so the whole clip is still one number.
        heat = rounds[0]
        lineup = [(b.name, b.color) for b in heat["balls"]]
        other = [c for c in LIVE_STAGES if c != heat["style"].stage] or list(LIVE_STAGES)
        final_stage = params.get("final_stage") or random.Random(seed ^ 0x5F3759DF).choice(other)
        rounds.append(run_round(seed + 104729, variant, {**params, "stage": final_stage},
                                  cfg, sim_w, sim_h, fps, lineup=lineup))

    clip_dir = work_dir
    clip_dir.mkdir(parents=True, exist_ok=True)

    # Captions: the heat states its measured stake; the final restates the
    # structure, never a result — the viewer just saw the heat, and naming
    # its winner again is one more word that is not a stake.
    hook_text = (params.get("hook_text") or "").strip() or default_hook(variant, rounds[0])
    overlays = [overlay(variant, sim_w, sim_h, fps, text=hook_text)]
    if len(rounds) > 1:
        overlays.append(overlay(variant, sim_w, sim_h, fps, text=FINAL_CAPTION))

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
                                    ask=closing_ask(sim_w, sim_h, fps),
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
            label = ("The heat" if i == 0 else "The final") if len(rounds) > 1 else f"{len(r['balls'])} marbles ({names}) race"
            if len(rounds) > 1:
                label += f" runs down {stage_text(r)}"
            else:
                label += f" down {stage_text(r)}"
            if r["winner"]:
                gap = (f", {seconds(r['margin_s'])} ahead of {r['runner_up']}" if r["runner_up"]
                       else f"; no other marble crosses in the next {POST_WIN_MAX_S} seconds")
                parts.append(f"{label}. The {r['winner']} marble reaches the bottom first, at "
                             f"{r['winner_frame'] / fps:.1f} seconds{gap}.")
            else:
                parts.append(f"{label}; none reaches the bottom within {r['duration_s']:.1f} seconds.")
        head = f"Two rounds, same {len(rounds[0]['balls'])} marbles ({names}). " if len(rounds) > 1 else ""
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
                 "gate": bool(r["style"].gates)}
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
            "runner_up": last["runner_up"],
            "margin_s": last["margin_s"],
            "hook_text": hook_text,
        },
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

    def generate(self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path) -> GeneratedClip:
        return generate(seed=seed, variant=variant, params=params, work_dir=work_dir)
