"""Turn impact events into the clip's soundtrack.

The point of an ASMR clip is the sound, so this is not decoration. Each impact
becomes a short decaying transient whose pitch and pan come from the object that
made it, mixed over a very quiet room tone so the clip is never dead silent.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48_000
# One pitch per object index. Minor pentatonic keeps repeated hits from
# sounding like a mistake when several objects land at once.
PITCHES = [196.0, 233.1, 261.6, 311.1, 349.2, 392.0]

# The four numbers that set how loud the finished track measures. They were
# swept together against ffmpeg's ebur128 rather than chosen by ear — see the
# loudness section of the README for what each one buys.
IMPACT_DECAY = 18.0  # 1/s; how long one hit rings. Lower = longer = louder.
TAIL_REFERENCE_DENSITY = 14.0  # hits per second that need no added tail
TAIL_MAX = 1.35  # cap on wet/dry; past this it stops sounding like a room
LIMIT_DRIVE = 3.6  # tanh drive; higher trades crest factor for loudness


@dataclass(frozen=True)
class Impact:
    t: float
    strength: float  # 0..1
    index: int  # which object hit
    pan: float  # -1 left .. 1 right


def _transient(strength: float, pitch: float) -> np.ndarray:
    # Long enough that the envelope has decayed to nothing before the buffer
    # ends; cutting a ring off mid-decay is an audible click of its own.
    length = int(SAMPLE_RATE * min(0.6, 6.0 / IMPACT_DECAY))
    t = np.arange(length) / SAMPLE_RATE
    env = np.exp(-t * IMPACT_DECAY)
    body = np.sin(2 * np.pi * pitch * t) * 0.6
    body += np.sin(2 * np.pi * pitch * 2.02 * t) * 0.25
    click = np.random.default_rng(int(pitch * 100)).normal(0, 1, length)
    click *= np.exp(-t * 320.0) * 0.45
    return (body + click) * env * np.clip(strength, 0.05, 1.0)


def _room_tone(length: int, rng: np.random.Generator) -> np.ndarray:
    noise = rng.normal(0, 1, length)
    # Cheap low-pass: a short moving average is enough for a bed you shouldn't notice.
    kernel = np.ones(220) / 220
    # Kept very low: the mux stage raises the whole track to the loudness target,
    # and a bed that is comfortable here becomes hiss after 12 dB of gain.
    return np.convolve(noise, kernel, mode="same") * 0.005


# Prime-ish delays in milliseconds, so the taps never line up into a flutter.
_TAPS = [(37, 0.46), (53, 0.38), (71, 0.31), (97, 0.24), (131, 0.17), (179, 0.11)]


def _tail_mix(impacts: int, duration_s: float) -> float:
    """How wet the tail should be, from how often something is hitting something.

    A funnel pouring 38 times a second needs almost none; four marbles hitting 7
    times a second need a lot, or the clip measures 4 dB below the loudness
    target and QC throws it out. Reference density is 14 hits per second.
    """
    density = impacts / max(duration_s, 0.001)
    return float(
        np.clip(0.42 * (TAIL_REFERENCE_DENSITY / max(density, 1.0)), 0.30, TAIL_MAX)
    )


def _tail(stereo: np.ndarray, mix: float) -> np.ndarray:
    """A short tapped-delay tail.

    Not an effect for its own sake. Isolated clicks measure around -26 LUFS
    integrated while peaking near full scale, and no normaliser can raise that
    without clipping — the energy simply is not there between the hits. A tail
    puts energy in the gaps, which is also what a real object in a real room
    sounds like.
    """
    wet = np.zeros_like(stereo)
    for delay_ms, gain in _TAPS:
        delay = int(SAMPLE_RATE * delay_ms / 1000)
        if delay >= len(stereo):
            continue
        wet[delay:] += stereo[:-delay] * gain
        # One extra bounce per tap, which is what makes the tail dense
        # rather than a set of audible echoes.
        if delay * 2 < len(stereo):
            wet[delay * 2 :] += stereo[: -delay * 2] * gain * 0.45
    return stereo + wet * mix


def _soft_limit(stereo: np.ndarray, drive: float | None = None, ceiling: float = 0.89) -> np.ndarray:
    """Round the peaks off so the average can come up without clipping."""
    if drive is None:
        drive = LIMIT_DRIVE
    peak = float(np.max(np.abs(stereo))) or 1.0
    normalised = stereo / peak
    shaped = np.tanh(normalised * drive) / np.tanh(drive)
    return shaped / (float(np.max(np.abs(shaped))) or 1.0) * ceiling


def render_wav(impacts: list[Impact], duration_s: float, out_path: Path) -> Path:
    length = int(SAMPLE_RATE * duration_s)
    rng = np.random.default_rng(1)
    left = _room_tone(length, rng)
    right = _room_tone(length, rng)

    for impact in impacts:
        start = int(impact.t * SAMPLE_RATE)
        if start >= length:
            continue
        pitch = PITCHES[impact.index % len(PITCHES)]
        sample = _transient(impact.strength, pitch)
        end = min(length, start + len(sample))
        sample = sample[: end - start]
        pan = float(np.clip(impact.pan, -1.0, 1.0))
        left[start:end] += sample * (0.5 - pan * 0.35)
        right[start:end] += sample * (0.5 + pan * 0.35)

    stereo = np.stack([left, right], axis=1)
    stereo = _tail(stereo, _tail_mix(len(impacts), duration_s))
    stereo = _soft_limit(stereo)

    pcm = (stereo * 32767).astype("<i2")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SAMPLE_RATE)
        fh.writeframes(pcm.tobytes())
    return out_path
