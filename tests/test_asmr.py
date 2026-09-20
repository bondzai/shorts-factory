"""BTC ASMR: the sound, the pacing, and the thing that nearly sank it.

The first version of this module scored 0.92 and 0.98 against a 0.88
sameness ceiling over eight seeds — every clip after the first would have
been rejected — because it varied coin count and tint, and the gate is an
8x8 average hash that sees neither. The layout tests below are what keep
that fixed.
"""

import math

import pytest

from factory import audio, settings
from factory.generators import asmr

W, H, FPS = 540, 960, 30
SECONDS = 18.0


def simulate(seed, variant="coin_pour", seconds=SECONDS):
    style = asmr._Style(seed=seed, variant=variant)
    style.backdrop = asmr.BACKDROPS[seed % len(asmr.BACKDROPS)]
    gen = asmr.CoinASMR()
    return gen._simulate(seed, variant, W, H, FPS, int(seconds * FPS), style, seconds)


# --- the module ---------------------------------------------------------------

def test_it_is_registered_and_ready():
    from factory import generators

    assert generators.all_generators()["asmr"].ready is True
    assert set(generators.all_generators()["asmr"].variants) == {"coin_pour", "coin_stack"}


def test_an_unknown_variant_names_what_exists(tmp_path):
    with pytest.raises(ValueError, match="coin_pour"):
        asmr.CoinASMR().generate(seed=1, variant="nope", params={}, work_dir=tmp_path)


def test_the_seed_fixes_the_run_and_different_seeds_diverge():
    a, b = simulate(4242)[0], simulate(4242)[0]
    assert a[-1] == b[-1]
    assert simulate(4242)[0][-1] != simulate(4243)[0][-1]


# --- pacing: the difference between ASMR and gravel ----------------------------

@pytest.mark.parametrize("variant,low,high", [("coin_pour", 3.0, 16.0), ("coin_stack", 0.8, 7.0)])
def test_the_hit_rate_stays_in_the_band_the_format_needs(variant, low, high):
    """Before the refractory period the pour ran at 74 hits a second, which
    measures louder and is much less pleasant. Density is the format."""
    for seed in (11, 4242, 7301):
        _, impacts, _ = simulate(seed, variant)
        rate = len(impacts) / SECONDS
        assert low <= rate <= high, (variant, seed, rate)


def test_a_coin_does_not_ring_twice_while_it_is_still_ringing():
    """A settling pile nudges its neighbours constantly; a disc already
    ringing does not answer each nudge with a fresh strike."""
    for variant in ("coin_pour", "coin_stack"):
        _, impacts, scene = simulate(4242, variant)
        by_pan: dict[tuple[int, int], float] = {}
        for im in impacts:
            key = (im.index, round(im.pan, 3))
            previous = by_pan.get(key)
            if previous is not None:
                assert im.t - previous >= asmr.RING_REFRACTORY_S - 1e-6, (variant, key)
            by_pan[key] = im.t


def test_every_impact_is_a_coin_and_none_land_past_the_end():
    _, impacts, _ = simulate(4242)
    assert impacts
    assert {im.timbre for im in impacts} == {"coin"}
    assert all(0 <= im.t < SECONDS for im in impacts)


# --- the sound itself ----------------------------------------------------------

def test_a_coin_rings_longer_than_a_marble_and_is_not_harmonic():
    import numpy as np

    def ring_out(name):
        x = audio._transient(1.0, 400.0, name)
        n = int(audio.SAMPLE_RATE * 0.01)
        env = np.sqrt((x[: len(x) // n * n].reshape(-1, n) ** 2).mean(axis=1))
        below = np.where(env < env.max() * 0.01)[0]
        return (below[0] * 0.01) if len(below) else len(x) / audio.SAMPLE_RATE

    assert ring_out("coin") > ring_out("marble") * 2
    ratios = [r for r, _ in audio.TIMBRES["coin"].partials]
    # A disc's modes are inharmonic; whole-number ratios are a xylophone.
    assert any(abs(r - round(r)) > 0.2 for r in ratios[1:])
    assert audio.TIMBRES["coin"].pitches != audio.TIMBRES["marble"].pitches


def test_an_unknown_timbre_falls_back_rather_than_failing():
    assert len(audio._transient(1.0, 400.0, "kazoo")) > 0


def test_the_marble_voice_is_untouched_by_the_default():
    """The loudness constants were swept against it, so a silent change here
    would move every race clip's measured loudness."""
    import numpy as np

    assert np.array_equal(audio._transient(0.7, 261.6), audio._transient(0.7, 261.6, "marble"))


# --- the bitcoin mark ----------------------------------------------------------

def test_the_bitcoin_mark_is_drawn_and_is_not_the_notdef_box():
    """Every font on the render machine answers U+20BF with .notdef, so the
    mark is strokes. This pins that it draws something, and something with
    the ticks that tell a B from a B-with-bars."""
    import numpy as np
    from PIL import Image, ImageDraw

    image = Image.new("L", (120, 120), 0)
    asmr._bitcoin_glyph(ImageDraw.Draw(image), 60, 60, 70, 255)
    pixels = np.array(image)
    assert pixels.sum() > 0
    rows = pixels.sum(axis=1)
    # The ticks put ink above and below the cap height, which a plain B has not.
    assert rows[:16].sum() > 0 and rows[-16:].sum() > 0


def test_a_coin_sprite_is_cached_and_has_transparent_corners():
    a = asmr._coin_sprite(30, (247, 147, 26), False)
    assert asmr._coin_sprite(30, (247, 147, 26), False) is a
    assert a.mode == "RGBA" and a.getpixel((0, 0))[3] == 0


# --- what the seed must actually vary ------------------------------------------

def _styles(variant, seeds):
    out = []
    for seed in seeds:
        style = asmr._Style(seed=seed, variant=variant)
        import random

        rng = random.Random(seed)
        style.backdrop = asmr.BACKDROPS[rng.randrange(len(asmr.BACKDROPS))]
        style.vessel = asmr._vessel_for(style.backdrop)
        out.append(style)
    return out


def test_the_room_is_sometimes_light_and_sometimes_dark():
    """Inverting the room flips every cell of the average hash at once, and
    it is the single strongest thing the seed can change."""
    lights = [s.light for s in _styles("coin_pour", range(40))]
    assert any(lights) and not all(lights)


def test_the_furniture_contrasts_with_whichever_room_it_is_in():
    dark, light = (18, 16, 22), (236, 231, 222)
    assert sum(asmr._vessel_for(dark)) > sum(dark)
    assert sum(asmr._vessel_for(light)) < sum(light)


def test_the_seed_moves_the_layout_not_just_the_coins():
    """Coin count and tint move no cell of an 8x8 hash. Position, size and
    shape do, so those have to come out different across seeds."""
    import random

    seen_shape, seen_floor, seen_half, seen_towers = set(), set(), set(), set()
    for seed in range(24):
        rng = random.Random(seed)
        style = asmr._Style(seed=seed, variant="coin_pour")
        scene = asmr._build_pour(__import__("pymunk").Space(), W, H, rng, style, SECONDS)
        seen_shape.add(style.shape)
        seen_floor.add(round(scene.profile[0][1] / H, 1))
        seen_half.add(round((scene.profile[-1][0] - scene.profile[0][0]) / W, 1))

        rng = random.Random(seed)
        style = asmr._Style(seed=seed, variant="coin_stack")
        asmr._build_stack(__import__("pymunk").Space(), W, H, rng, style, SECONDS)
        seen_towers.add(style.towers)

    assert seen_shape == set(asmr.VESSEL_SHAPES)
    assert len(seen_floor) >= 4, seen_floor
    assert len(seen_half) >= 3, seen_half
    assert seen_towers == {1, 2, 3}


def test_a_pile_is_never_asked_to_stand_taller_than_the_frame():
    import random

    for seed in range(24):
        rng = random.Random(seed)
        style = asmr._Style(seed=seed, variant="coin_pour")
        scene = asmr._build_pour(__import__("pymunk").Space(), W, H, rng, style, SECONDS)
        # The vessel fills from its lowest point, which for a bowl or a vee
        # is the middle of the profile, not the rim the first point sits on.
        floor = min(y for _, y in scene.profile)
        half = (scene.profile[-1][0] - scene.profile[0][0]) / 2
        capacity = (H * 0.94 - floor) * half * 2 * 0.62 / (math.pi * style.radius ** 2)
        assert style.coins <= max(12, capacity) + 1, (seed, style.coins, capacity)


# --- what it says it is --------------------------------------------------------

def test_the_description_says_what_happened_and_nothing_about_money(sandbox, tmp_path):
    clip = asmr.CoinASMR().generate(seed=4242, variant="coin_pour",
                                    params={"seconds": 11.0}, work_dir=tmp_path)
    text = clip.description.lower()
    assert "bitcoin symbol" in text and "no text on screen" in text
    for word in ("price", "worth", "value", "buy", "sell", "invest", "moon", "profit"):
        assert word not in text, word
    assert clip.facts["timbre"] == "coin"
    assert clip.facts["coins"] == clip.facts["coins"] and clip.facts["impacts"] > 0
    assert 10.0 <= clip.duration_s <= 12.0


def test_an_asmr_title_is_not_judged_for_spoilers_it_cannot_have(sandbox):
    """The result-language gate exists for races. A clip with no race has no
    result, and "it took 40 coins" is not a spoiler."""
    from factory import pipeline

    assert pipeline.spoiler({"coins": 40, "timbre": "coin"}, title="It took 40 coins to fill the glass") is None
    assert pipeline.spoiler({"winner": "red", "finishes": {"red": 1.0, "blue": 2.0}},
                            title="Red took it") is not None
