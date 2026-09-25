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
class Timbre:
    """What kind of object made the sound.

    A marble is a small dense sphere: a short thud with a near-harmonic body.
    A coin is a thin metal disc, and a disc does not ring in harmonics — its
    modes are inharmonic (1, 1.59, 2.14, 2.30, 2.65, 3.16 are the first
    Chladni ratios of a free circular plate), the high modes die away first,
    and the whole thing rings far longer than a marble. Using a harmonic
    series for a coin is what makes cheap sound design read as a xylophone.
    """

    partials: tuple[tuple[float, float], ...]  # (frequency ratio, amplitude)
    decay: float  # 1/s, the fundamental's decay
    high_bias: float  # extra decay per unit of ratio; higher modes die first
    click_decay: float
    click_level: float
    pitches: tuple[float, ...]


TIMBRES: dict[str, Timbre] = {
    # Unchanged from the version the loudness constants were swept against.
    "marble": Timbre(
        partials=((1.0, 0.6), (2.02, 0.25)),
        decay=IMPACT_DECAY, high_bias=0.0, click_decay=320.0, click_level=0.45,
        pitches=tuple(PITCHES),
    ),
    # Metal disc. An octave above the marbles so the two never sound like the
    # same object, and quiet on the click so a long clip is not fatiguing —
    # ASMR is listened to at volume, and a bright transient that is pleasant
    # once is painful forty times.
    "coin": Timbre(
        partials=((1.0, 0.5), (1.594, 0.3), (2.136, 0.2), (2.296, 0.15), (2.653, 0.1), (3.156, 0.07)),
        decay=5.5, high_bias=1.9, click_decay=900.0, click_level=0.22,
        pitches=(392.0, 466.2, 523.3, 622.3, 698.5, 784.0),
    ),
}


@dataclass(frozen=True)
class Impact:
    t: float
    strength: float  # 0..1
    index: int  # which object hit
    pan: float  # -1 left .. 1 right
    timbre: str = "marble"


def _transient(strength: float, pitch: float, timbre: str = "marble") -> np.ndarray:
    # Long enough that the envelope has decayed to nothing before the buffer
    # ends; cutting a ring off mid-decay is an audible click of its own.
    spec = TIMBRES.get(timbre) or TIMBRES["marble"]
    length = int(SAMPLE_RATE * min(1.2, 6.0 / spec.decay))
    t = np.arange(length) / SAMPLE_RATE
    body = np.zeros(length)
    for ratio, amplitude in spec.partials:
        # Each mode gets its own envelope, so the sound grows darker as it
        # decays the way a struck object does, rather than fading as a block.
        body += np.sin(2 * np.pi * pitch * ratio * t) * amplitude * np.exp(
            -t * (spec.decay + spec.high_bias * (ratio - 1.0))
        )
    click = np.random.default_rng(int(pitch * 100)).normal(0, 1, length)
    click *= np.exp(-t * spec.click_decay) * spec.click_level
    return (body + click * np.exp(-t * spec.decay)) * np.clip(strength, 0.05, 1.0)


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


def whoosh(seconds: float = 0.6) -> np.ndarray:
    """An ignite: noise through a low-pass whose cutoff sweeps up, over a
    short rising tone, swelling in and dying away. Synthesised, like every
    other sound here; the seed is fixed, so it is the same whoosh every time."""
    n = int(SAMPLE_RATE * seconds)
    t = np.arange(n) / SAMPLE_RATE
    noise = np.random.default_rng(11).normal(0, 1, n)
    # One-pole low-pass, cutoff 250 Hz -> 5 kHz: the sweep is the "whoo".
    cutoff = 250.0 * (5000.0 / 250.0) ** np.clip(t / (seconds * 0.7), 0, 1)
    alpha = 1 - np.exp(-2 * np.pi * cutoff / SAMPLE_RATE)
    out = np.empty(n)
    acc = 0.0
    for k in range(n):
        acc += alpha[k] * (noise[k] - acc)
        out[k] = acc
    out /= float(np.max(np.abs(out))) or 1.0
    peak = 0.22
    env = np.where(t < peak, (t / peak) ** 2, np.exp(-(t - peak) * 9.0))
    tone = np.sin(2 * np.pi * np.cumsum(120.0 + 260.0 * t / seconds) / SAMPLE_RATE) * 0.25
    return (out * 0.75 + tone) * env


def thump(seconds: float = 0.5) -> np.ndarray:
    """A low hit under the opening's slow-mo: a sine falling 95 -> 42 Hz with
    a fast decay and a soft click on the front."""
    n = int(SAMPLE_RATE * seconds)
    t = np.arange(n) / SAMPLE_RATE
    freq = 42.0 + 53.0 * np.exp(-t * 14.0)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.exp(-t * 8.0)
    click = np.random.default_rng(12).normal(0, 1, n) * np.exp(-t * 320.0) * 0.25
    return body + click


SOUNDS = {"whoosh": whoosh, "thump": thump}


def render_wav(impacts: list[Impact], duration_s: float, out_path: Path,
               sounds: list[tuple[float, str, float]] | None = None) -> Path:
    """`sounds`: (t, kind, gain) of the presentation's own sounds (SOUNDS),
    mixed centre; None leaves the track exactly as it was without them."""
    length = int(SAMPLE_RATE * duration_s)
    rng = np.random.default_rng(1)
    left = _room_tone(length, rng)
    right = _room_tone(length, rng)

    for impact in impacts:
        start = int(impact.t * SAMPLE_RATE)
        if start >= length:
            continue
        spec = TIMBRES.get(impact.timbre) or TIMBRES["marble"]
        pitch = spec.pitches[impact.index % len(spec.pitches)]
        sample = _transient(impact.strength, pitch, impact.timbre)
        end = min(length, start + len(sample))
        sample = sample[: end - start]
        pan = float(np.clip(impact.pan, -1.0, 1.0))
        left[start:end] += sample * (0.5 - pan * 0.35)
        right[start:end] += sample * (0.5 + pan * 0.35)

    for t, kind, gain in sounds or ():
        start = int(t * SAMPLE_RATE)
        if not 0 <= start < length:
            continue
        sample = SOUNDS[kind]() * gain
        end = min(length, start + len(sample))
        left[start:end] += sample[: end - start] * 0.5
        right[start:end] += sample[: end - start] * 0.5

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
