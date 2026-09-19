"""ffmpeg and ffprobe plumbing. Frames go in over a pipe, an mp4 comes out."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Iterator


class FfmpegMissing(RuntimeError):
    pass


def require_ffmpeg() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FfmpegMissing("ffmpeg and ffprobe are required: brew install ffmpeg")
    return ffmpeg, ffprobe


def encode_frames(
    frames: Iterable[bytes],
    *,
    out_path: Path,
    src_size: tuple[int, int],
    out_size: tuple[int, int],
    fps: int,
) -> Path:
    """Pipe raw rgb24 frames into libx264. `frames` yields w*h*3 bytes each."""
    ffmpeg, _ = require_ffmpeg()
    src_w, src_h = src_size
    out_w, out_h = out_size
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{src_w}x{src_h}", "-r", str(fps), "-i", "-",
        "-vf", f"scale={out_w}:{out_h}:flags=lanczos",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for frame in frames:
            proc.stdin.write(frame)
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg encode failed with code {proc.returncode}")
    return out_path


def _measure_loudnorm(audio: Path, target_lufs: float) -> dict | None:
    """First loudnorm pass: measure the source so the second pass can be exact."""
    ffmpeg, _ = require_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(audio),
         "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    start = result.stderr.rfind("{")
    end = result.stderr.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return json.loads(result.stderr[start : end + 1])
    except json.JSONDecodeError:
        return None


def mux(video: Path, audio: Path, out_path: Path, target_lufs: float | None = None) -> Path:
    """Combine the silent video with its audio, normalised to the QC target.

    Peak normalisation in the synthesiser is not enough: a track of sparse
    transients peaks near full scale while measuring -26 LUFS integrated, which
    QC rejects and rightly so. Single-pass loudnorm only recovered 4 dB of that,
    because it cannot see the whole file before it starts. Measuring first and
    feeding the numbers back lands on the target.
    """
    ffmpeg, _ = require_ffmpeg()
    if target_lufs is None:
        from . import settings

        target_lufs = float(settings.load().qc["target_lufs"])

    filter_spec = f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
    measured = _measure_loudnorm(audio, target_lufs)
    if measured:
        filter_spec += (
            f":measured_I={measured['input_i']}"
            f":measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-i", str(video), "-i", str(audio),
            "-af", filter_spec,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(out_path),
        ],
        check=True,
    )
    return out_path


def probe(path: Path) -> dict:
    _, ffprobe = require_ffmpeg()
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    num, _, den = stream["r_frame_rate"].partition("/")
    fps = float(num) / float(den or 1)
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(fps, 3),
        "duration_s": round(float(data["format"]["duration"]), 3),
    }


def loudness_lufs(path: Path) -> float | None:
    """Integrated loudness via ebur128. None when the file has no audio."""
    ffmpeg, _ = require_ffmpeg()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    matches = re.findall(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS", result.stderr)
    if not matches:
        return None
    return float(matches[-1])


def sample_frames(path: Path, at_seconds: Iterable[float]) -> list[bytes]:
    """Grab single PNG frames. Used by QC — cheap and enough to see the hook."""
    ffmpeg, _ = require_ffmpeg()
    out: list[bytes] = []
    for t in at_seconds:
        result = subprocess.run(
            [ffmpeg, "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(path),
             "-frames:v", "1", "-f", "image2", "-c:v", "png", "-"],
            check=True, capture_output=True,
        )
        if result.stdout:
            out.append(result.stdout)
    return out


def iter_frame_bytes(images: Iterable) -> Iterator[bytes]:
    """PIL images -> raw rgb24 bytes."""
    for image in images:
        yield image.convert("RGB").tobytes()
