"""Channel artwork, drawn from the same palette as the clips.

Branding that does not look like the content is a small lie the viewer notices
before they can say why, so the avatar and banner are built from the generator's
own colours and geometry rather than designed separately.

Two constraints do the real work here:

  Avatar   YouTube crops it to a circle and shows it at 32px in a feed. Anything
           with more than about three elements turns to mush at that size, so
           this is three marbles and one ramp, nothing else.
  Banner   The image is 2048x1152, but only the centre 1235x338 is visible on
           every device. Everything that must be read lives inside that box;
           everything outside it is decoration that phone viewers never see.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .generators.physics import BACKGROUND, RACE_COLORS, STRUCTURE

AVATAR = 800
BANNER = (2048, 1152)
SAFE = (1235, 338)  # visible on every device, centred
DIM = (143, 143, 163)

FONT_CANDIDATES = [
    ("/System/Library/Fonts/Avenir Next.ttc", 2),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path, index in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _marble(draw: ImageDraw.ImageDraw, x: float, y: float, r: float, color) -> None:
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
    draw.ellipse(
        [x - r * 0.42, y - r * 0.55, x - r * 0.06, y - r * 0.19],
        fill=tuple(min(255, c + 60) for c in color),
    )


def _tracked_text(
    draw: ImageDraw.ImageDraw, text: str, font, tracking: int, centre_x: int, y: int, fill
) -> None:
    """Draw letter-spaced text centred on centre_x. PIL has no tracking of its own."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = centre_x - total / 2
    for ch, width in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += width + tracking


def avatar(path: Path) -> Path:
    # Lifted off the clips' own background: at #12121a the circle disappears
    # into a dark-mode page, and an avatar you cannot find the edge of reads as
    # a missing image.
    image = Image.new("RGB", (AVATAR, AVATAR), (27, 27, 38))
    draw = ImageDraw.Draw(image)
    draw.ellipse([8, 8, AVATAR - 8, AVATAR - 8], outline=STRUCTURE, width=12)

    # One ramp, kept inside the circular crop. The whole group is positioned so
    # its centre of mass lands on the middle of the image, not the middle of the
    # ramp — an off-centre composition is obvious once YouTube cuts the circle.
    ramp_start, ramp_end = (150, 372), (650, 592)
    draw.line([ramp_start, ramp_end], fill=STRUCTURE, width=30)

    # Three marbles descending it. Three is the most that still reads at 32px.
    radius = 92
    slope = (ramp_end[1] - ramp_start[1]) / (ramp_end[0] - ramp_start[0])
    for i, (_, color) in enumerate(RACE_COLORS[:3]):
        x = 222 + i * 178
        y = ramp_start[1] + (x - ramp_start[0]) * slope - radius - 14
        _marble(draw, x, y, radius, color)

    image.save(path)
    return path


def banner(path: Path, title: str = "GRAVITY LAB", tagline: str = "no talking  ·  sound on") -> Path:
    width, height = BANNER
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    safe_top = (height - SAFE[1]) // 2
    safe_bottom = safe_top + SAFE[1]

    # Decoration lives in the bands above and below the safe area, so it never
    # competes with the words and never gets cropped into them on a phone. It is
    # a zigzag at the same slope the generator uses (~0.37); flatter than that
    # and it stops reading as a track and becomes stray lines.
    drop = 180
    segment = 482
    for band_top in (150, safe_bottom + 60):
        points = []
        for i in range(5):
            points.append((60 + i * segment, band_top + (drop if i % 2 else 0)))
        draw.line(points, fill=STRUCTURE, width=10, joint="curve")
        for i in range(4):
            start, end = points[i], points[i + 1]
            if end[1] < start[1]:
                continue  # marbles sit on the descending segments only
            t = 0.42
            mx = start[0] + (end[0] - start[0]) * t
            my = start[1] + (end[1] - start[1]) * t - 32
            _marble(draw, mx, my, 27, RACE_COLORS[(i + band_top) % len(RACE_COLORS)][1])

    title_font = _font(132)
    tagline_font = _font(46)
    centre = width // 2
    _tracked_text(draw, title, title_font, 14, centre, safe_top + 80, (232, 232, 239))
    tagline_width = draw.textlength(tagline, font=tagline_font)
    draw.text(
        (centre - tagline_width / 2, safe_top + 236), tagline, font=tagline_font, fill=DIM
    )

    image.save(path)
    return path


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return [avatar(out_dir / "avatar.png"), banner(out_dir / "banner.png")]
