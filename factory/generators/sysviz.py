"""Crypto / systems generator — one concept per clip, typed out, no narration.

The split that makes this module safe to publish:

  The prose is hand-written.  Headlines, row labels and claim lines live in
                              data/concepts/*.json and are versioned. No model
                              writes them, per clip or ever.

  The numbers are computed.   Every hash, prime, exponent and bit count comes
                              from hashlib and pow() at render time, derived
                              from the clip's seed. Nothing on screen is typed
                              in by hand or invented.

That leaves no room for either party to be confidently wrong. A viewer with a
Python shell can reproduce any frame in ten seconds, which is the only claim the
channel makes for itself.

`consensus_round` was in the original plan and is not here. "Consensus" is a
family of protocols with different assumptions, and a fifteen-second animation
of nodes voting teaches whichever one the viewer already half-remembers. It was
replaced by `merkle_root`, which is the same visual idea — state changes
propagate upward — and is arithmetic rather than interpretation.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from PIL import Image, ImageDraw, ImageFont

from .. import audio, render, settings
from .base import GeneratedClip, register

CHARS_PER_IMPACT = 2  # a keystroke every other character; see audio._tail_mix
LEAD_IN = 0.02  # share of the clip the headline holds alone; see README, "the first second"
HOLD_OUT = 0.16  # share held on the finished screen at the end

BACKGROUND = (12, 13, 18)
INK = (233, 235, 242)
DIM = (112, 116, 133)
ACCENT = (255, 190, 72)  # a character that differs from the compared row
MATCH = (124, 196, 128)  # a character that agrees, in "same" mode
RULE = (34, 36, 46)

MONO_CANDIDATES = [
    ("/System/Library/Fonts/Menlo.ttc", 0),
    ("/System/Library/Fonts/SFNSMono.ttf", 0),
    ("/System/Library/Fonts/Monaco.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
]
SANS_CANDIDATES = [
    ("/System/Library/Fonts/Helvetica.ttc", 0),
    ("/System/Library/Fonts/SFNS.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]


def _font(candidates: list[tuple[str, int]], size: int) -> ImageFont.FreeTypeFont:
    for path, index in candidates:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    raise RuntimeError(
        "sysviz needs a TrueType font and found none of: "
        + ", ".join(p for p, _ in candidates)
    )


# --- the concept library ------------------------------------------------------


@dataclass
class Concept:
    id: str
    variant: str
    engine: str
    headline: str
    footer: str
    rows: list[dict[str, Any]]
    claim: str
    spec: dict[str, Any] = field(default_factory=dict)


def concepts_dir() -> Path:
    override = settings.load().db_path.parent / "concepts"
    if override.exists():
        return override
    return Path(__file__).resolve().parents[2] / "data" / "concepts"


def load_concepts(variant: str | None = None) -> list[Concept]:
    directory = concepts_dir()
    out: list[Concept] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}: {exc}") from None
        missing = {"id", "variant", "engine", "headline", "rows", "claim"} - set(raw)
        if missing:
            raise ValueError(f"{path.name}: missing {sorted(missing)}")
        out.append(
            Concept(
                id=raw["id"],
                variant=raw["variant"],
                engine=raw["engine"],
                headline=raw["headline"],
                footer=raw.get("footer", ""),
                rows=raw["rows"],
                claim=raw["claim"],
                spec=raw,
            )
        )
    if variant is not None:
        out = [c for c in out if c.variant == variant]
    return out


# --- engines: the arithmetic --------------------------------------------------
# Each returns (slots shown on screen, facts recorded with the clip). Facts are
# what QC and the metadata agent are allowed to make claims from.


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _bit_difference(hex_a: str, hex_b: str) -> int:
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")


def sha256_avalanche(rng: random.Random, spec: dict[str, Any]):
    words = spec.get("words") or ["marble"]
    stem = rng.choice(words)
    numeric = bool(spec.get("numeric"))
    input_a = f"{stem}{rng.randint(1000, 9999)}" if numeric else f"{stem}{rng.randint(10, 99)}"

    # Flip exactly one character, and say so on screen only because it is true.
    position = rng.randrange(len(stem), len(input_a)) if numeric else rng.randrange(len(input_a))
    original = input_a[position]
    alphabet = "0123456789" if original.isdigit() else "abcdefghijklmnopqrstuvwxyz"
    replacement = rng.choice([c for c in alphabet if c != original])
    input_b = input_a[:position] + replacement + input_a[position + 1 :]

    hash_a, hash_b = _sha(input_a), _sha(input_b)
    bits = _bit_difference(hash_a, hash_b)
    return (
        {
            "input_a": input_a,
            "input_b": input_b,
            "hash_a": hash_a,
            "hash_b": hash_b,
            "bits": f"{bits} of 256",
        },
        {"bits_changed": bits, "input_a": input_a, "input_b": input_b,
         "hash_a": hash_a, "hash_b": hash_b},
    )


def diffie_hellman(rng: random.Random, spec: dict[str, Any]):
    primes = spec.get("primes") or [[2027, 2]]
    p, g = rng.choice(primes)
    a = rng.randint(120, p - 120)
    b = rng.randint(120, p - 120)
    sent_a, sent_b = pow(g, a, p), pow(g, b, p)
    shared_a, shared_b = pow(sent_b, a, p), pow(sent_a, b, p)
    if shared_a != shared_b:  # pragma: no cover - modular arithmetic, or a bug
        raise ValueError(f"diffie_hellman: {shared_a} != {shared_b} for p={p} g={g}")
    return (
        {
            "public": f"p = {p}   g = {g}",
            "secret_a": f"a = {a}",
            "secret_b": f"b = {b}",
            "sent_a": f"A = {sent_a}",
            "sent_b": f"B = {sent_b}",
            "shared_a": f"{shared_a}",
            "shared_b": f"{shared_b}",
            "shared": f"{shared_a}",
        },
        {"p": p, "g": g, "a": a, "b": b, "shared": shared_a},
    )


def merkle_root(rng: random.Random, spec: dict[str, Any]):
    def node(text: str) -> str:
        return _sha(text)[:16]

    ids = [f"tx-{rng.randint(1000, 9999)}" for _ in range(4)]

    def tree(records: list[str]):
        level0 = [node(r) for r in records]
        level1 = [node(level0[0] + level0[1]), node(level0[2] + level0[3])]
        return level0, level1, node(level1[0] + level1[1])

    level0, level1, root = tree(ids)

    edited = list(ids)
    index = rng.randrange(4)
    edited[index] = f"tx-{rng.randint(1000, 9999)}"
    while edited[index] == ids[index]:  # pragma: no cover - 1 in 9000
        edited[index] = f"tx-{rng.randint(1000, 9999)}"
    _, _, root_b = tree(edited)

    changed = sum(1 for x, y in zip(root, root_b) if x != y)
    return (
        {
            "leaves": " ".join(ids),
            "leaves_b": " ".join(edited),
            "level0": "".join(level0),
            "level1": "".join(level1),
            "root": root,
            "root_b": root_b,
            "changed": str(changed),
        },
        {"records": ids, "edited_index": index, "root": root, "root_b": root_b,
         "hex_digits_changed": changed},
    )


ENGINES: dict[str, Callable[[random.Random, dict[str, Any]], tuple[dict[str, str], dict]]] = {
    "sha256_avalanche": sha256_avalanche,
    "diffie_hellman": diffie_hellman,
    "merkle_root": merkle_root,
}


# --- layout -------------------------------------------------------------------


@dataclass
class Line:
    """One physical line of value text, with where it sits and what it compares to."""

    text: str
    compare: str  # same length or shorter; "" means no comparison
    mode: str  # "diff" or "same"
    y: float
    x: float
    emphasis: bool


@dataclass
class Style:
    """What changes between two clips of the same concept.

    Measured, not decorative. With a fixed layout the sameness gate accepted 1
    of 25 sysviz clips: the average hash works on an 8x8 grey grid and cannot
    see which characters changed, only where the light and dark areas are. So
    the knobs here are the ones that move that grid — how the hex wraps, how
    big it is, where the column sits — rather than colour, which barely
    registers in greyscale.
    """

    wrap: int  # hex characters per line: 8, 16 or 32 all divide a 64-char digest
    align: str  # "left" or "center"
    anchor: str  # "top", or "center" to spread the slack between blocks
    scale: float  # multiplier on the fitted monospace size
    rules: bool  # hairline under each block
    panels: bool  # a filled card behind each block
    margin: float  # share of the width kept clear at each edge
    background: tuple[int, int, int]
    accent: tuple[int, int, int]
    panel: tuple[int, int, int]


PALETTES = [
    ((12, 13, 18), (255, 190, 72), (30, 31, 40)),
    ((16, 14, 20), (255, 138, 96), (38, 32, 42)),
    ((11, 16, 20), (104, 206, 240), (26, 36, 44)),
    ((18, 14, 14), (250, 160, 160), (42, 30, 30)),
    ((13, 17, 15), (150, 225, 140), (28, 38, 30)),
    ((15, 13, 21), (196, 160, 255), (34, 29, 46)),
    ((236, 234, 228), (168, 74, 20), (255, 255, 252)),  # the light one; see README
]


def style_for(rng: random.Random) -> Style:
    background, accent, panel = rng.choice(PALETTES)
    return Style(
        wrap=rng.choice([8, 16, 16, 32]),
        align=rng.choice(["left", "left", "center"]),
        anchor=rng.choice(["top", "center"]),
        scale=rng.choice([0.72, 0.84, 1.0]),
        rules=rng.random() < 0.4,
        panels=rng.random() < 0.5,
        margin=rng.choice([0.05, 0.065, 0.10]),
        background=background,
        accent=accent,
        panel=panel,
    )


def _is_light(colour: tuple[int, int, int]) -> bool:
    return sum(colour) / 3 > 128


@dataclass
class Block:
    label: str
    label_y: float
    lines: list[Line]


def _wrap(text: str, width: int | None) -> list[str]:
    if not width:
        return [text]
    return [text[i : i + width] for i in range(0, len(text), width)] or [""]


def _row_wrap(row: dict[str, Any], value: str, style: Style | None) -> int | None:
    """Restyle only the hex rows; re-wrapping a row of words would split tokens."""
    declared = row.get("wrap")
    if style is None or not declared:
        return declared
    if len(value) % 16 == 0 and all(c in "0123456789abcdef" for c in value):
        return style.wrap
    return declared


def _layout(
    concept: Concept, slots: dict[str, str], sim_w: int, sim_h: int,
    style: Style | None = None,
):
    """Place every row, shrinking the monospace font until the whole thing fits.

    Laid out once at final size and then revealed, so nothing on screen moves.
    A row that grew downward as it filled would make the clip feel like a
    terminal log; this is meant to read like a page being filled in.
    """
    margin = int(sim_w * (style.margin if style else 0.065))
    top = int(sim_h * 0.055)
    bottom = int(sim_h * 0.94)

    ceiling = int(46 * (style.scale if style else 1.0))
    for mono_size in range(ceiling, 13, -2):
        mono = _font(MONO_CANDIDATES, mono_size)
        label = _font(SANS_CANDIDATES, max(15, int(mono_size * 0.46)))
        head = _font(SANS_CANDIDATES, max(22, int(mono_size * 0.72)))
        foot = _font(SANS_CANDIDATES, max(13, int(mono_size * 0.38)))

        char_w = mono.getlength("0")
        widest = max(
            len(l)
            for row in concept.rows
            for l in _wrap(slots[row["slot"]], _row_wrap(row, slots[row["slot"]], style))
        )
        if char_w * widest > sim_w - margin * 2:
            continue

        head_lines = concept.headline.split("\n")
        head_h = len(head_lines) * (mono_size * 0.86)
        y = top + head_h + mono_size * 0.9

        blocks: list[Block] = []
        for row in concept.rows:
            block = Block(label=row["label"], label_y=y, lines=[])
            y += mono_size * 0.62
            reference = slots.get(row.get("compare", ""), "")
            wrap = _row_wrap(row, slots[row["slot"]], style)
            ref_lines = _wrap(reference, wrap) if reference else []
            for i, text in enumerate(_wrap(slots[row["slot"]], wrap)):
                x = margin
                if style and style.align == "center":
                    x = (sim_w - char_w * len(text)) / 2
                block.lines.append(
                    Line(
                        text=text,
                        compare=ref_lines[i] if i < len(ref_lines) else "",
                        mode=row.get("mode", "diff"),
                        y=y,
                        x=x,
                        emphasis=bool(row.get("emphasis")),
                    )
                )
                y += mono_size * 1.14
            y += mono_size * (0.78 if (style and style.panels) else 0.46)
            blocks.append(block)

        if y < bottom:
            if style and style.anchor == "center" and len(blocks) > 1:
                # Spread the slack between the blocks rather than pushing the
                # whole column down: one lump of empty space under the headline
                # reads as a mistake, even spacing reads as a designed page.
                step = (bottom - y) / (len(blocks) - 1)
                for i, block in enumerate(blocks):
                    block.label_y += step * i
                    for line in block.lines:
                        line.y += step * i
            return blocks, mono, label, head, foot, head_lines, top, margin

    raise ValueError(f"sysviz: concept {concept.id!r} does not fit the frame")


# --- the generator ------------------------------------------------------------


class SystemViz:
    name = "sysviz"
    variants = ["hash_avalanche", "key_exchange", "merkle_root"]
    ready = True
    blurb = (
        "One cryptography concept per clip, typed out on screen, no narration. "
        "hash_avalanche flips one character of an input and counts the output "
        "bits that move; key_exchange runs Diffie-Hellman on small primes; "
        "merkle_root edits one record and shows the root change. Every number is "
        "computed at render time from hashlib and pow(), and the wording comes "
        "from a hand-written concept library."
    )

    def generate(
        self, *, seed: int, variant: str, params: dict[str, Any], work_dir: Path
    ) -> GeneratedClip:
        if variant not in self.variants:
            raise ValueError(f"{self.name}: unknown variant {variant!r}")
        cfg = settings.load().render
        out_w, out_h = int(cfg["width"]), int(cfg["height"])
        scale = float(cfg["render_scale"])
        sim_w, sim_h = int(out_w * scale), int(out_h * scale)
        fps = int(cfg["fps"])
        seconds = float(params.get("seconds", 15.0))
        frames_total = int(seconds * fps)

        rng = random.Random(seed)
        concept = self._pick_concept(rng, variant, params.get("concept"))
        slots, facts = ENGINES[concept.engine](rng, concept.spec)
        style = style_for(rng)

        layout = _layout(concept, slots, sim_w, sim_h, style)
        blocks = layout[0]
        reveal, impacts = self._script(blocks, frames_total, fps)
        duration_s = frames_total / fps

        work_dir.mkdir(parents=True, exist_ok=True)
        wav = audio.render_wav(impacts, duration_s, work_dir / "audio.wav")
        silent = render.encode_frames(
            self._frames(concept, layout, reveal, sim_w, sim_h, style),
            out_path=work_dir / "video.mp4",
            src_size=(sim_w, sim_h),
            out_size=(out_w, out_h),
            fps=fps,
        )
        final = render.mux(silent, wav, work_dir / "clip.mp4")

        claim = concept.claim.format(**slots)
        description = (
            f"{concept.headline.replace(chr(10), ' ')} {claim} The values are "
            f"computed at render time rather than scripted: "
            f"{self._verify_hint(concept, facts)} Typed out on screen over "
            f"{duration_s:.1f} seconds with no narration."
        )

        return GeneratedClip(
            video_path=final,
            duration_s=duration_s,
            description=description,
            facts={
                "variant": variant,
                "seed": seed,
                "concept": concept.id,
                "engine": concept.engine,
                "impacts": len(impacts),
                "style": f"{style.wrap}/{style.align}/{style.anchor}/{style.scale}",
                **facts,
            },
        )

    def _pick_concept(self, rng: random.Random, variant: str, wanted: str | None) -> Concept:
        pool = load_concepts(variant)
        if wanted:
            for concept in load_concepts():
                if concept.id == wanted:
                    return concept
            have = [c.id for c in load_concepts()]
            raise ValueError(f"no concept {wanted!r}; have {have or 'none'}")
        if not pool:
            raise ValueError(f"no concept file for variant {variant!r} in {concepts_dir()}")
        return rng.choice(pool)

    def _verify_hint(self, concept: Concept, facts: dict) -> str:
        """A one-line recipe so a viewer can check the clip, in the description."""
        if concept.engine == "sha256_avalanche":
            return (
                f"sha256(\"{facts['input_a']}\") and sha256(\"{facts['input_b']}\") "
                f"differ in {facts['bits_changed']} bits."
            )
        if concept.engine == "diffie_hellman":
            return (
                f"pow({facts['g']}, {facts['a']} * {facts['b']}, {facts['p']}) "
                f"= {facts['shared']}."
            )
        return (
            f"the root moves from {facts['root']} to {facts['root_b']} when one "
            f"of the four records changes."
        )

    def _script(self, blocks: list[Block], frames_total: int, fps: int):
        """How many characters of each line are visible on each frame, and the sounds.

        One transient every other character, which lands near the density
        audio._tail_mix is tuned around. Pitch follows the character itself, so
        a hash sounds different from the one above it.
        """
        sequence: list[tuple[int, int]] = []  # (line index, char index)
        lines = [line for block in blocks for line in block.lines]
        for i, line in enumerate(lines):
            for j in range(len(line.text)):
                sequence.append((i, j))

        start = int(frames_total * LEAD_IN)
        end = int(frames_total * (1.0 - HOLD_OUT))
        span = max(1, end - start)

        reveal: list[list[int]] = []
        impacts: list[audio.Impact] = []
        typed_before = 0
        for frame in range(frames_total):
            progress = (frame - start) / span
            typed = int(max(0.0, min(1.0, progress)) * len(sequence))
            counts = [0] * len(lines)
            for i, j in sequence[:typed]:
                counts[i] = j + 1
            reveal.append(counts)

            for index in range(typed_before, typed):
                if index % CHARS_PER_IMPACT:
                    continue
                line_index, char_index = sequence[index]
                line = lines[line_index]
                char = line.text[char_index]
                impacts.append(
                    audio.Impact(
                        t=frame / fps,
                        strength=0.85 if line.emphasis else 0.6,
                        index=int(char, 16) % 6 if char in "0123456789abcdef" else ord(char) % 6,
                        pan=(char_index % 9) / 8.0 * 1.4 - 0.7,
                    )
                )
            typed_before = typed
        return reveal, impacts

    def _frames(self, concept, layout, reveal, sim_w: int, sim_h: int, style=None) -> Iterator[bytes]:
        blocks, mono, label_font, head_font, foot_font, head_lines, top, margin = layout
        lines = [line for block in blocks for line in block.lines]
        char_w = mono.getlength("0")
        line_height = head_font.size * 1.2
        background = style.background if style else BACKGROUND
        accent = style.accent if style else ACCENT
        light = _is_light(background)
        ink = (24, 24, 30) if light else INK
        dim = (128, 126, 120) if light else DIM
        rule = (214, 210, 202) if light else RULE
        match = (36, 128, 62) if light else MATCH

        for counts in reveal:
            image = Image.new("RGB", (sim_w, sim_h), background)
            draw = ImageDraw.Draw(image)

            if style and style.panels:
                for block in blocks:
                    if not block.lines:
                        continue
                    draw.rounded_rectangle(
                        [
                            margin * 0.45,
                            block.label_y - mono.size * 0.34,
                            sim_w - margin * 0.45,
                            block.lines[-1].y + mono.size * 1.24,
                        ],
                        radius=mono.size * 0.34,
                        fill=style.panel,
                    )

            y = top
            for text in head_lines:
                draw.text((margin, y), text, font=head_font, fill=ink)
                y += line_height

            cursor = 0
            for block in blocks:
                visible = any(counts[cursor + i] for i in range(len(block.lines)))
                draw.text(
                    (margin, block.label_y),
                    block.label.upper(),
                    font=label_font,
                    fill=dim if visible else rule,
                )
                for line in block.lines:
                    shown = counts[cursor]
                    cursor += 1
                    for i in range(shown):
                        char = line.text[i]
                        colour = ink
                        if line.compare and i < len(line.compare):
                            differs = line.compare[i] != char
                            if line.mode == "same" and not differs:
                                colour = match
                            elif line.mode == "diff" and differs:
                                colour = accent
                        draw.text(
                            (line.x + char_w * i, line.y), char, font=mono, fill=colour
                        )
                    if 0 < shown < len(line.text):
                        draw.rectangle(
                            [
                                line.x + char_w * shown,
                                line.y + mono.size * 0.16,
                                line.x + char_w * (shown + 0.82),
                                line.y + mono.size * 1.02,
                            ],
                            fill=accent,
                        )
                if style and style.rules and block.lines:
                    rule_y = block.lines[-1].y + mono.size * 1.34
                    draw.line([(margin, rule_y), (sim_w - margin, rule_y)], fill=rule, width=1)

            if concept.footer:
                draw.text(
                    (margin, sim_h * 0.955),
                    concept.footer.upper(),
                    font=foot_font,
                    fill=rule,
                )
            yield image.tobytes()


register(SystemViz())
