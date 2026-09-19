"""Crypto / system visual generator — slot three, not built yet.

This is the module that builds authority rather than views: one concept per clip
(hash avalanche, key exchange, consensus round, cache eviction), animated, no
narration. Lowest policy risk of the three because every clip has its own
editorial intent instead of being one template reseeded.

To finish it:
  1. Choose the renderer. Manim gives you good maths typography but is slow and
     shells out; writing the frames with PIL/cairo like physics.py keeps the
     pipeline uniform. Start with PIL — the shapes here are boxes, arrows and
     hex strings.
  2. Represent a concept as data, not as code: a list of steps with what changes
     on screen at each one. Then one renderer draws any concept in the library.
  3. Audio is keyboard/mechanical transients per step plus a quiet bed. Reuse
     audio.Impact.
  4. Set ready = True.

Keep a hand-written library of concepts under data/concepts/. Letting the model
invent the concept per clip is how you end up publishing a confident, wrong
explanation of a consensus protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import GeneratedClip, register


class SystemViz:
    name = "sysviz"
    variants = ["hash_avalanche", "key_exchange", "consensus_round"]
    ready = False
    blurb = (
        "Animated explanation of one systems or cryptography concept, no talking. "
        "Highest CPM, lowest saturation. Not implemented yet."
    )

    def generate(
        self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path
    ) -> GeneratedClip:
        raise NotImplementedError(
            "sysviz is a stub: see the module docstring for the four steps"
        )


register(SystemViz())
