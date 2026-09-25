"""The presentation (factory/generators/physics/present.py): camera, time
remapping, fire and HUD over a race it never changes.

The promises: off, a race renders exactly what it did before (pinned hashes
from the code before it existed); on, it is still a function of the seed,
the time map is monotonic and shows every source frame outside the one fast
stretch, the clip stays inside QC's length, the HUD stays inside a narrow
frame and off Shorts' right-hand strip, and a redraw from the trace is the
shipped frame.
"""

import hashlib
import json
import math
import platform
import sys

import numpy as np
import pytest

from factory import audio, settings
from factory.generators import physics
from factory.generators.physics import present, replay
from factory.series import trace

CAST = [
    {"id": "blaze", "name": "Blaze", "color": "#E84C4A", "traits": {"friction": 0.10, "mass_mult": 0.88}},
    {"id": "tide", "name": "Tide", "color": "#378ADD", "traits": {"friction": 0.28, "mass_mult": 1.2}},
    {"id": "volt", "name": "Volt", "color": "#F2C230", "traits": {"jitter": 3.0, "radius_mult": 0.95}},
    {"id": "moss", "name": "Moss", "color": "#97C459", "traits": {}},
]


@pytest.fixture
def hashed(sandbox, monkeypatch):
    """Encode nothing; keep a hash of every frame and of them all."""
    seen = {"frames": [], "all": None}

    def encode_frames(frames, *, out_path, src_size, out_size, fps):
        whole = hashlib.sha256()
        seen["frames"] = []
        for frame in frames:
            whole.update(frame)
            seen["frames"].append(hashlib.sha256(frame).hexdigest())
        seen["all"] = whole.hexdigest()
        out_path.write_bytes(b"")
        return out_path

    monkeypatch.setattr(physics.sandbox.encoder, "encode_frames", encode_frames)
    monkeypatch.setattr(physics.sandbox.encoder, "mux", lambda video, audio, out: out)
    return seen


def _race(tmp_path, name, seed=11, engine="pygame", **params):
    settings.load().raw["render"]["engine"] = engine
    params = {"stage": "lodestone", "rounds": 1, "cast": CAST, **params}
    return physics.generate(seed=seed, variant="marble_race", params=params, work_dir=tmp_path / name)


def _off():
    settings.load().raw["presentation"]["enabled"] = False


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- off is today ------------------------------------------------------------------

# Frames (all of them, hashed in order), audio.wav, the facts and trace.json of
# races rendered on main at cd841c0, before the presentation existed. Off, the
# same races must give the same bytes. Per platform, as test_mechanics pins.
PINS = {
    ("darwin", "arm64"): {
        "lodestone-cast": {
            "frames": "c90955e12d204a482b12b1351a0454245f5989663483c73a4c8897455173d3c0",
            "wav": "6483da85b8925424aeb17cec89bf2977e9a3132c2c4b8c4e93e3abb0574c0273",
            "facts": "68acf8b3fdabd66c9599edfceb07462a637b5143acc244cbddc3529dc858fb85",
            "npz": "e005964b4198a87c66064f053cacf4c6e607f11cd1eff253236ce0cd3a22c4a3",
            "json": "de816dfeaf9649432f77a7bfa0eb18476c157389771193bab2d6e1c39235af5d",
        },
        "rockers-pil": {
            "frames": "e7f196c4d6de1e989060b7d068cde8e7476f91468d2c4221c0d77c9d049431da",
            "wav": "18d3f5dd051bf804ebe7909a2f3aff8ff1fb369476a3e7f1a71c838dee187d79",
            "facts": "62842c8cb8271ea4a5f6f9e7a48d731e77c128ca94ad131eb19783444d2c9660",
            "npz": "0482f3192452aad61fd2bcf613c98f92b0b059400484a92d099645322453efa7",
            "json": "efc71d34d01f6c3578cf36631eec46d31be3c66e4f19e297a4f0d22842296281",
        },
    },
}
PINNED = {
    "lodestone-cast": ("pygame", 11, {"stage": "lodestone", "rounds": 1, "cast": CAST}),
    "rockers-pil": ("pil", 3, {"stage": "rockers", "rounds": 1}),
}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_off_renders_byte_for_byte_what_it_did_before(hashed, tmp_path, name):
    pins = PINS.get((sys.platform, platform.machine()))
    if pins is None:
        pytest.skip(f"no pins recorded for {sys.platform}/{platform.machine()}")
    _off()
    engine, seed, params = PINNED[name]
    settings.load().raw["render"]["engine"] = engine
    clip = physics.generate(seed=seed, variant="marble_race", params=params, work_dir=tmp_path / name)
    folder = clip.trace_path.parent
    facts = hashlib.sha256(json.dumps([clip.facts, clip.description, clip.duration_s], sort_keys=True,
                                      default=str).encode()).hexdigest()
    got = {"frames": hashed["all"], "wav": _sha(folder / "audio.wav"), "facts": facts,
           "npz": _sha(folder / trace.NPZ), "json": _sha(folder / trace.JSON)}
    assert got == pins[name]
    assert "presentation" not in clip.facts


def test_a_config_without_the_block_is_off(sandbox):
    settings.load().raw.pop("presentation", None)
    assert present.config() is None


def test_the_funnel_is_never_presented(hashed, tmp_path):
    clip = physics.generate(seed=5, variant="funnel_drop", params={}, work_dir=tmp_path / "f")
    assert "presentation" not in clip.facts
    assert "presentation" not in trace.read(clip.trace_path)[1]


# --- on: deterministic, and redrawn exactly ------------------------------------------

def test_the_same_seed_gives_the_same_frames_and_time_map(hashed, tmp_path):
    a = _race(tmp_path, "a")
    frames_a = hashed["all"]
    b = _race(tmp_path, "b")
    assert hashed["all"] == frames_a
    for name in (trace.NPZ, trace.JSON, "audio.wav"):
        assert (a.trace_path.parent / name).read_bytes() == (b.trace_path.parent / name).read_bytes()
    assert a.facts["presentation"] == b.facts["presentation"]


@pytest.mark.parametrize("engine", ["pygame", "pil"])
def test_a_redraw_is_the_shipped_frame(hashed, tmp_path, engine):
    clip = _race(tmp_path, engine, engine=engine, rounds=2)
    shipped = list(hashed["frames"])
    arrays, meta = trace.read(clip.trace_path)
    assert "presentation" in meta and "round1_timemap" in arrays
    redrawn = [hashlib.sha256(f).hexdigest() for f in physics.PhysicsSandbox().redraw(clip.trace_path.parent)]
    assert redrawn == shipped
    heat = len(arrays["round0_timemap"])
    one = heat + 40
    frame = physics.redraw_frame(clip.trace_path.parent, 1, 40)
    assert hashlib.sha256(frame).hexdigest() == shipped[one]


def test_raw_is_the_race_without_the_presentation(hashed, tmp_path):
    """The long-form's edit: every source frame once, drawn as the clip would
    have shipped with the presentation off."""
    clip = _race(tmp_path, "on")
    arrays, _ = trace.read(clip.trace_path)
    raw = [hashlib.sha256(f).hexdigest() for f in physics.PhysicsSandbox().redraw(clip.trace_path.parent, raw=True)]
    assert len(raw) == len(arrays["round0_positions"])
    _off()
    _race(tmp_path, "off")
    assert raw == hashed["frames"]


def test_the_long_form_asks_for_the_raw_race(sandbox, monkeypatch, tmp_path):
    from factory import seasons

    calls = []

    class Gen:
        def redraw(self, trace_dir, raw=False):
            calls.append(raw)
            return iter(())

    monkeypatch.setattr("factory.generators.get", lambda name: Gen())
    seasons.redraw({"generator": "physics", "presentation": {}}, tmp_path, raw=True)
    seasons.redraw({"generator": "physics"}, tmp_path, raw=True)  # an older trace: nothing to take off
    assert calls == [True, False]


# --- the time map ----------------------------------------------------------------------

def test_the_time_map_is_monotonic_and_shows_every_source_frame(hashed, tmp_path):
    clip = _race(tmp_path, "tm", rounds=2)
    arrays, meta = trace.read(clip.trace_path)
    fps = meta["fps"]
    for n in range(2):
        tm = arrays[f"round{n}_timemap"]
        src = tm[:, 0]
        frames = len(arrays[f"round{n}_positions"])
        assert src[0] == 0 and src[-1] == frames - 1
        steps = np.diff(src)
        assert (steps > 0).all(), "the source clock never stops or runs back"
        fast = set()
        for k in np.nonzero(steps > 1.0 + 1e-9)[0]:
            fast.update(range(int(math.floor(src[k])) + 1, int(math.ceil(src[k + 1]))))
        shown = {int(math.floor(s + 1e-9)) for s in src} | {int(math.ceil(s - 1e-9)) for s in src}
        assert set(range(frames)) - fast <= shown
        assert (tm[:, 1] >= 1.0).all()
        # The camera never looks past the stage's edge.
        z, cx, cy = tm[:, 1], tm[:, 2], tm[:, 3]
        w, h = meta["sim_w"], meta["sim_h"]
        assert (cx - w / (2 * z) >= -1e-6).all() and (cx + w / (2 * z) <= w + 1e-6).all()
        assert (cy - h / (2 * z) >= -1e-6).all() and (cy + h / (2 * z) <= h + 1e-6).all()
    moments = clip.facts["presentation"]["rounds"]
    hit = moments[0]["hit"]
    assert hit["window_out_s"][0] < 2.5
    zoom = settings.load().raw["presentation"]["zoom"]
    first, last = arrays["round0_timemap"][0], arrays["round1_timemap"][-1]
    assert first[1] == pytest.approx(zoom) and last[1] == pytest.approx(zoom), "the loop's two ends are framed alike"
    punches = [p["out_s"] for p in moments[1]["punch_ins"]]
    assert all(b - a >= 1.5 - 1e-9 for a, b in zip(punches, punches[1:]))
    assert "finish" in moments[1] and "finish" not in moments[0]
    assert fps == 30


def test_the_clip_stays_inside_qc_length_and_facts_stay_in_source_time(hashed, tmp_path):
    qc = settings.load().qc
    on = _race(tmp_path, "on", rounds=2)
    shown = on.facts["presentation"]["output_s"]
    assert qc["min_seconds"] <= on.duration_s <= qc["max_seconds"]
    assert shown == pytest.approx(on.duration_s, abs=0.01)
    assert len(hashed["frames"]) == round(on.duration_s * 30)
    _off()
    off = _race(tmp_path, "off", rounds=2)
    assert on.facts["rounds"] == off.facts["rounds"] and on.facts["finishes"] == off.facts["finishes"]
    assert on.facts["outcome"] == off.facts["outcome"]
    assert on.duration_s > off.duration_s


def _views(tmp_path, rounds=2):
    from factory.generators.physics import sandbox

    cfg = settings.load().render
    rs = sandbox.race_rounds(11, "marble_race", {"stage": "lodestone", "rounds": rounds, "cast": CAST}, cfg, 540, 960, 30)
    labels = present.labels_for(rs[0]["balls"], CAST)
    return rs, [present.view_of(r, labels) for r in rs]


def test_over_the_max_the_finish_slowmo_gives_way_first(sandbox, tmp_path):
    _, views = _views(tmp_path)
    cfg = present.config()
    free = present.direct(views, 30, 540, 960, cfg, max_s=999)
    assert free["finish_window_s"] == present.FINISH_WINDOW_S and free["hit"]
    tight = present.direct(views, 30, 540, 960, cfg, max_s=free["output_s"] - 0.3)
    assert tight["hit"] and tight["finish_window_s"] < present.FINISH_WINDOW_S
    assert tight["output_s"] <= free["output_s"] - 0.3
    tighter = present.direct(views, 30, 540, 960, cfg, max_s=free["source_s"])
    assert tighter["finish_window_s"] == 0 and not tighter["hit"]


def test_impacts_follow_the_time_map_and_keep_their_pitch(sandbox, tmp_path):
    rs, views = _views(tmp_path, rounds=1)
    cfg = present.config()
    plan = present.direct(views, 30, 540, 960, cfg, max_s=999)
    plan["meta"] = present.trace_meta(cfg, {}, rs, plan)
    shown, sounds = present.soundtrack(rs, plan, 30)
    assert [(i.strength, i.index, i.pan) for i in shown] == [(i.strength, i.index, i.pan) for i in rs[0]["impacts"]]
    S = plan["maps"][0][:, 0]
    a, b = plan["moments"][0]["hit"]["window_src_s"]
    inside = [(im, sh) for im, sh in zip(rs[0]["impacts"], shown) if a + 0.02 < im.t < b - 0.02]
    for (i1, s1), (i2, s2) in zip(inside, inside[1:]):
        assert s2.t - s1.t == pytest.approx((i2.t - i1.t) / cfg["slowmo"], abs=0.04)
    assert sounds[0][:2] == (0.0, "whoosh")
    if plan["moments"][0]["hit"]["out_s"] is not None:
        assert sounds[1][1] == "thump"
    assert all(t2.t >= t1.t for t1, t2 in zip(sorted(shown, key=lambda i: i.t), sorted(shown, key=lambda i: i.t)[1:]))
    assert present.out_time(0.0, S, 30) == 0.0


def test_the_synthesised_sounds_are_original_and_fixed(tmp_path):
    for kind in ("whoosh", "thump"):
        one, two = audio.SOUNDS[kind](), audio.SOUNDS[kind]()
        assert np.array_equal(one, two) and np.max(np.abs(one)) > 0.1
    base = audio.render_wav([], 1.0, tmp_path / "a.wav")
    same = audio.render_wav([], 1.0, tmp_path / "b.wav", sounds=None)
    assert base.read_bytes() == same.read_bytes()
    loud = audio.render_wav([], 1.0, tmp_path / "c.wav", sounds=[(0.0, "whoosh", 0.55)])
    assert loud.read_bytes() != base.read_bytes()


# --- the HUD ---------------------------------------------------------------------------

@pytest.mark.parametrize("w,h", [(375, 667), (540, 960)])
@pytest.mark.parametrize("count", [2, 4, 5, 12])
def test_the_hud_is_inside_a_narrow_frame_and_off_the_right_strip(sandbox, w, h, count):
    lay = present.layout(w, h, count)
    for x, y, rw, rh in [lay["bar"], lay["tower"], *lay["rows"]]:
        assert 0 <= x and x + rw <= w * 0.88 and 0 <= y and y + rh <= h
    tx, ty, tw, th = lay["tower"]
    assert tx + tw <= w / 2, "the tower is on the left"
    assert ty >= h * 0.30 and ty + th <= h * 0.70, "between the closing ask and the caption"
    # Chips for marbles anywhere, in view or not, zoomed or not.
    points = [(-80, 300), (w + 50, 200), (w / 2, 5), (w / 2 + 3, 8), (10, h - 5), (w - 4, h / 2)][: max(2, count)]
    for cam in [(1.0, 0.0, 0.0), (1.9, w * 0.2, 0.0), (1.25, w * 0.1, h * 0.1)]:
        rects = present.chip_rects(points, [(90, 26)] * len(points), [20] * len(points), cam, w, h)
        for x, y, cw, ch, pointer in rects:
            tip = present.chip_tip(ch)
            assert 0 <= x - tip and x + cw + tip <= w * 0.88
            assert 0 <= y - tip and y + ch + tip <= h
        assert rects[0][4] == "left" and rects[1][4] == "right"


@pytest.mark.parametrize("w,h", [(375, 667), (540, 960)])
def test_the_caption_slams_in_without_leaving_the_frame(sandbox, w, h):
    from factory.generators.physics.text import overlay

    for text in ("PICK ONE", "WHICH ONE IS YOURS?", "FINAL · RUN IT BACK"):
        cap = overlay("marble_race", w, h, 30, text=text)
        from factory.generators import fx

        fx.init()
        surf = fx.text_surface(cap[0], cap[1].size, w * 0.9)
        widest = max(present.slam_scale(k / 30, surf.get_width(), w) for k in range(30)) * surf.get_width()
        assert widest <= w * 0.98 + 1
        assert present.slam_scale(0.0, surf.get_width(), w) > 1.0
        assert present.slam_scale(present.SLAM_S, surf.get_width(), w) == 1.0


def test_the_leaderboard_is_current_order_only(sandbox, tmp_path):
    rs, views = _views(tmp_path, rounds=1)
    v = views[0]
    first = present.standings(v, 0.0, 0)
    ys = v.states[0][:, 1]
    assert first == sorted(range(len(v.names)), key=lambda i: (ys[i], i))
    end = len(v.states) - 1
    last = present.standings(v, float(end), end)
    crossed = sorted(v.finishes, key=lambda n: (v.finishes[n], v.names.index(n)))
    assert [v.names[i] for i in last[: len(crossed)]] == crossed
    labels = present.labels_for(rs[0]["balls"], None)
    assert labels["blaze"] == "BLAZE"
    teams = present.labels_for([type("B", (), {"name": "blaze.2"})()], CAST)
    assert teams == {"blaze.2": "Blaze 2"}


def test_disabling_fire_and_leaderboard_is_honoured(hashed, tmp_path):
    _race(tmp_path, "full")
    full = list(hashed["frames"])
    raw = settings.load().raw["presentation"]
    raw["fire"] = False
    raw["leaderboard"] = False
    clip = _race(tmp_path, "bare")
    assert len(hashed["frames"]) == len(full) and hashed["frames"] != full
    _, meta = trace.read(clip.trace_path)
    assert meta["presentation"]["config"]["fire"] is False
    redrawn = [hashlib.sha256(f).hexdigest() for f in replay.redraw(clip.trace_path.parent)]
    assert redrawn == hashed["frames"]
