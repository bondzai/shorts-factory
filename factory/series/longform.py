"""Long-form videos redrawn from traces: a tournament or a recap, 16:9.

Nothing is re-simulated and no short is concatenated. Each level's race is
redrawn from its trace by its own generator — a `Redraw` the caller supplies,
since the series package never imports one —
set in the centre of a 1920x1080 frame with the level and the standings in
panels either side, and its impacts are re-synthesised from the trace. The
pieces are encoded as segments with identical codec settings and joined
without re-encoding, which keeps Python's share of the work to the redraw
itself.

A tournament runs every level whole: a title card, the race, the table after
it. A recap runs a title card, the last seconds of each race, and what the
race changed in the table. A `sleep` compilation is deliberately not here
(docs/08 §7).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from PIL import Image, ImageDraw

from .. import audio, settings
from ..brand import _font
from ..render import require_ffmpeg
from . import cast as cast_mod
from . import standings
from . import trace as trace_mod
from .cast import level_number

W, H = 1920, 1080
CARD_S = 2.5
TABLE_S = 3.5
RECAP_TAIL_S = 7.0
BG = (14, 15, 20)
PANEL = (24, 26, 34)
INK = (235, 235, 242)
DIM = (143, 143, 163)
KINDS = ("tournament", "recap")

# (trace meta, trace directory, raw=True) -> the race's frames at sim size.
# A long-form asks for the raw race: a short's presentation (camera, slow-mo,
# its HUD) is that short's edit, and this is a different one — every source
# frame once, in real time, as the trace's impacts and frame count assume.
Redraw = Callable[..., Iterator[bytes]]


@dataclass
class Piece:
    level_id: str
    world: str
    clip_id: str
    title: str
    trace_dir: Path
    meta: dict[str, Any]
    colors: list[tuple[int, int, int]]
    frames: int  # across all rounds


def _next_level(level_id: str) -> str:
    return f"L{level_number(level_id) + 1:02d}"


def pieces(conn: sqlite3.Connection, channel_id: str, season, level_ids: list[str]) -> list[Piece]:
    """The approved or published clip of each level, with its trace, in order."""
    out: list[Piece] = []
    for level_id in level_ids:
        level = season.level(level_id)
        row = conn.execute(
            """SELECT id, title, trace_path, status FROM clips
               WHERE channel_id = ? AND level_id = ? AND deleted_at IS NULL
                 AND status IN ('approved', 'published') AND trace_path IS NOT NULL
               ORDER BY created_at DESC LIMIT 1""",
            (channel_id, level_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"{level_id} has no approved clip with a trace; approve one first")
        trace_path = Path(row["trace_path"])
        if not trace_path.is_absolute():
            trace_path = settings.ROOT / trace_path
        arrays, meta = trace_mod.read(trace_path)
        rounds = sum(1 for k in arrays if k.endswith("_positions"))
        frames = sum(arrays[f"round{i}_positions"].shape[0] for i in range(rounds))
        out.append(Piece(level_id, level.world, row["id"], row["title"] or level_id, trace_path.parent,
                         meta, [tuple(int(c) for c in rgb) for rgb in arrays["colors"]], frames))
    return out


def _names(channel_id: str) -> dict[str, str]:
    c = cast_mod.load(channel_id)
    return {e.id: e.name for e in c.entrants} if c else {}


def _table(conn, channel_id: str, season_id: str, before: str) -> list[dict]:
    return standings.table(conn, channel_id, season_id, before_level=before)


# --- drawing ---------------------------------------------------------------

def _chips(draw: ImageDraw.ImageDraw, x: int, y: int, ids: list[str], colors, names: dict[str, str],
           size: int = 44) -> None:
    font = _font(size)
    for i, (eid, rgb) in enumerate(zip(ids, colors)):
        cy = y + i * int(size * 1.6)
        r = size * 0.42
        draw.ellipse([x, cy - r + size * 0.55, x + 2 * r, cy + r + size * 0.55], fill=rgb)
        draw.text((x + 2 * r + 18, cy), names.get(eid, eid.title()), font=font, fill=INK)


def _table_lines(draw: ImageDraw.ImageDraw, x: int, y: int, rows: list[dict], heading: str,
                 size: int = 38, width: int = 560) -> None:
    draw.text((x, y), heading, font=_font(size - 8), fill=DIM)
    font = _font(size)
    for i, row in enumerate(rows[:10]):
        yy = y + 70 + i * int(size * 1.5)
        draw.text((x, yy), f"{i + 1}  {row['name']}", font=font, fill=INK)
        pts = str(row["points"])
        draw.text((x + width - draw.textlength(pts, font=font), yy), pts, font=font, fill=INK)


def card(piece: Piece, names: dict[str, str], season_title: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((160, 170), season_title.upper(), font=_font(40), fill=DIM)
    d.text((160, 230), piece.level_id, font=_font(150), fill=INK)
    d.text((160, 420), piece.world.replace("-", " ").title(), font=_font(64), fill=INK)
    d.text((160, 520), piece.title, font=_font(40), fill=DIM)
    _chips(d, 1180, 250, piece.meta["entrant_ids"], piece.colors, names)
    return img


def panel(piece: Piece, names: dict[str, str], rows: list[dict], race_w: int) -> Image.Image:
    """The frame around the race: level on the left, the table on the right."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    side = (W - race_w) // 2
    d.rectangle([0, 0, side - 1, H], fill=PANEL)
    d.rectangle([side + race_w, 0, W, H], fill=PANEL)
    d.text((70, 90), piece.level_id, font=_font(96), fill=INK)
    d.text((70, 215), piece.world.replace("-", " ").title(), font=_font(40), fill=DIM)
    _chips(d, 70, 330, piece.meta["entrant_ids"], piece.colors, names, size=40)
    _table_lines(d, side + race_w + 70, 90, rows, "STANDINGS BEFORE THIS RACE", width=side - 140)
    return img


def table_card(piece: Piece, before: list[dict], after: list[dict], recap: bool) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((160, 120), f"After {piece.level_id}", font=_font(88), fill=INK)
    _table_lines(d, 160, 290, after, "STANDINGS", size=46, width=820)
    if recap:
        was = {r["entrant_id"]: r["points"] for r in before}
        font = _font(46)
        for i, row in enumerate(after[:10]):
            gain = row["points"] - was.get(row["entrant_id"], 0)
            if gain:
                d.text((1100, 290 + 70 + i * 69), f"+{gain}", font=font, fill=(151, 196, 89))
    return img


# --- encoding --------------------------------------------------------------

def _ffmpeg(args: list[str]) -> None:
    ffmpeg, _ = require_ffmpeg()
    proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", *args], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[-400:]}")


VIDEO = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "{fps}"]
AUDIO = ["-c:a", "aac", "-b:a", "160k", "-ar", str(audio.SAMPLE_RATE), "-ac", "2"]


def _still(img: Image.Image, seconds: float, out: Path, fps: int, preset: str) -> Path:
    png = out.with_suffix(".png")
    img.save(png)
    _ffmpeg(["-loop", "1", "-framerate", str(fps), "-t", f"{seconds:.3f}", "-i", str(png),
             "-f", "lavfi", "-t", f"{seconds:.3f}", "-i", f"anullsrc=r={audio.SAMPLE_RATE}:cl=stereo",
             *[a.format(fps=fps) for a in VIDEO], "-preset", preset, *AUDIO, "-shortest", str(out)])
    png.unlink()
    return out


def _impacts(piece: Piece) -> list[audio.Impact]:
    fps = int(piece.meta["fps"])
    out: list[audio.Impact] = []
    offset = 0.0
    arrays, _ = trace_mod.read(piece.trace_dir)
    for i, rnd in enumerate(piece.meta["rounds"]):
        for t, strength, index, pan in rnd.get("impacts", []):
            out.append(audio.Impact(t + offset, strength, int(index), pan))
        offset += arrays[f"round{i}_positions"].shape[0] / fps
    return out


def _race(piece: Piece, backdrop: Image.Image, race_w: int, out: Path, preset: str,
          redraw: Redraw, first_frame: int = 0) -> Path:
    """The redrawn race over its panel; frames before `first_frame` are drawn
    (the renderer is sequential) but not encoded."""
    fps = int(piece.meta["fps"])
    sim_w, sim_h = int(piece.meta["sim_w"]), int(piece.meta["sim_h"])
    kept = piece.frames - first_frame
    seconds = kept / fps
    wav = out.with_suffix(".wav")
    audio.render_wav([audio.Impact(im.t - first_frame / fps, im.strength, im.index, im.pan)
                      for im in _impacts(piece) if im.t >= first_frame / fps], seconds, wav)
    bg = out.with_suffix(".png")
    backdrop.save(bg)
    x = (W - race_w) // 2
    ffmpeg, _ = require_ffmpeg()
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{sim_w}x{sim_h}", "-r", str(fps), "-i", "-",
           "-loop", "1", "-framerate", str(fps), "-i", str(bg),
           "-i", str(wav),
           "-filter_complex", f"[0:v]scale={race_w}:{H}:flags=bilinear[race];[1:v][race]overlay={x}:0:shortest=1[v]",
           "-map", "[v]", "-map", "2:a",
           *[a.format(fps=fps) for a in VIDEO], "-preset", preset, *AUDIO, "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for i, frame in enumerate(redraw(piece.meta, piece.trace_dir, raw=True)):
            if i >= first_frame:
                proc.stdin.write(frame)
    finally:
        proc.stdin.close()
    err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed on {piece.level_id}: {err[-400:]}")
    wav.unlink()
    bg.unlink()
    return out


def _duration(path: Path) -> float:
    _, ffprobe = require_ffmpeg()
    out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def render(conn: sqlite3.Connection, channel_id: str, season, level_ids: list[str], kind: str, *,
           redraw: Redraw, out_dir: Path | None = None, preset: str = "faster") -> dict[str, Any]:
    """Render a long-form video; returns the paths and the chapter list."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}; sleep compilations are not built (docs/08 §7)")
    parts = pieces(conn, channel_id, season, level_ids)
    names = _names(channel_id)
    first, last = level_ids[0], level_ids[-1]
    out_dir = out_dir or settings.load().out_dir / channel_id / "longform" / f"{season.id}-{kind}-{first}-{last}"
    work = out_dir / "segments"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    segments: list[Path] = []
    chapters: list[tuple[float, str]] = []
    clock = 0.0
    for n, piece in enumerate(parts):
        fps = int(piece.meta["fps"])
        sim_w, sim_h = int(piece.meta["sim_w"]), int(piece.meta["sim_h"])
        race_w = int(round(H * sim_w / sim_h / 2) * 2)
        before = _table(conn, channel_id, season.id, piece.level_id)
        after = _table(conn, channel_id, season.id, _next_level(piece.level_id))
        chapters.append((clock, f"{piece.level_id} · {piece.title}"))
        seq = [_still(card(piece, names, season.title), CARD_S, work / f"{n:03d}a.mp4", fps, preset)]
        tail = max(0, piece.frames - int(RECAP_TAIL_S * fps)) if kind == "recap" else 0
        seq.append(_race(piece, panel(piece, names, before, race_w), race_w, work / f"{n:03d}b.mp4", preset, redraw, tail))
        seq.append(_still(table_card(piece, before, after, kind == "recap"), TABLE_S, work / f"{n:03d}c.mp4", fps, preset))
        for s in seq:
            clock += _duration(s)
        segments += seq

    listing = work / "list.txt"
    listing.write_text("".join(f"file '{s.name}'\n" for s in segments))
    video = out_dir / f"{out_dir.name}.mp4"
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(video)])
    shutil.rmtree(work)

    chapter_text = "".join(f"{stamp(t)} {label}\n" for t, label in chapters)
    (out_dir / "chapters.txt").write_text(chapter_text)
    final = _table(conn, channel_id, season.id, _next_level(last))
    table = "\n".join(f"{i + 1}. {r['name']} — {r['points']} pts ({r['wins']} wins in {r['races']})"
                      for i, r in enumerate(final))
    heading = {"tournament": "Every race", "recap": "The story so far"}[kind]
    description = (f"{season.title}, {first} to {last}: {heading.lower()}, redrawn from the original "
                   f"simulations.\n\nStandings after {last}:\n{table}\n\nChapters:\n{chapter_text}")
    (out_dir / "description.txt").write_text(description)
    return {"video": video, "chapters": out_dir / "chapters.txt", "description": out_dir / "description.txt",
            "duration_s": round(clock, 2), "levels": [p.level_id for p in parts],
            "rendered_at": dt.datetime.now().isoformat(timespec="seconds")}

