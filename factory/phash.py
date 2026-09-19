"""Perceptual hashing, used as the template-sameness guard.

A channel that uploads 300 clips cut from one template is the exact shape
YouTube's inauthentic-content policy describes. So every clip gets hashed at
four points in time and compared against every clip already in the database;
too similar is a hard reject, decided in code, not by the model.
"""

from __future__ import annotations

import io

from PIL import Image

HASH_BITS = 64
_HEX_PER_FRAME = HASH_BITS // 4


def ahash(png_bytes: bytes) -> str:
    """Average hash of one frame as 16 hex characters."""
    with Image.open(io.BytesIO(png_bytes)) as image:
        small = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    # mode "L" packs one byte per pixel in row order, so tobytes() is the data.
    pixels = list(small.tobytes())
    mean = sum(pixels) / len(pixels)
    bits = 0
    for i, value in enumerate(pixels):
        if value >= mean:
            bits |= 1 << i
    return f"{bits:016x}"


def clip_hash(frames: list[bytes]) -> str:
    """Concatenated per-frame hashes, so timing differences count too."""
    if not frames:
        raise ValueError("need at least one frame to hash")
    return "".join(ahash(frame) for frame in frames)


def _hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def similarity(a: str, b: str) -> float:
    """0..1 over the frames the two hashes have in common."""
    n = min(len(a), len(b)) // _HEX_PER_FRAME
    if n == 0:
        return 0.0
    scores = []
    for i in range(n):
        start, end = i * _HEX_PER_FRAME, (i + 1) * _HEX_PER_FRAME
        distance = _hamming(a[start:end], b[start:end])
        scores.append(1.0 - distance / HASH_BITS)
    return sum(scores) / len(scores)


def max_similarity(candidate: str, existing: list[str]) -> float:
    return max((similarity(candidate, other) for other in existing), default=0.0)
