import io

from PIL import Image

from factory import phash, settings
from factory.agents import qc
from factory.models import QCVerdict


def _png(color, size=(64, 64)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _good_probe():
    render = settings.load().render
    return {
        "width": render["width"],
        "height": render["height"],
        "fps": render["fps"],
        "duration_s": 18.0,
    }


def _verdict(**overrides):
    base = dict(
        verdict="pass",
        hook_strength=4,
        looks_templated=False,
        policy_risk="low",
        reasons=["marbles are already moving on the first frame"],
    )
    base.update(overrides)
    return QCVerdict(**base)


def test_clean_clip_has_no_hard_failures():
    assert qc.hard_failures(probe=_good_probe(), loudness_lufs=-14.0, sameness=0.1) == []


def test_horizontal_video_fails():
    probe = _good_probe() | {"width": 1920, "height": 1080}
    failures = qc.hard_failures(probe=probe, loudness_lufs=-14.0, sameness=0.1)
    assert any("vertical" in f for f in failures)


def test_silent_clip_fails():
    failures = qc.hard_failures(probe=_good_probe(), loudness_lufs=None, sameness=0.1)
    assert any("audio" in f for f in failures)


def test_duration_bounds():
    short = qc.hard_failures(
        probe=_good_probe() | {"duration_s": 4.0}, loudness_lufs=-14.0, sameness=0.1
    )
    long = qc.hard_failures(
        probe=_good_probe() | {"duration_s": 90.0}, loudness_lufs=-14.0, sameness=0.1
    )
    assert any("too short" in f for f in short)
    assert any("too long" in f for f in long)


def test_template_sameness_is_a_hard_failure():
    failures = qc.hard_failures(probe=_good_probe(), loudness_lufs=-14.0, sameness=0.97)
    assert any("too similar" in f for f in failures)


def test_decide_passes_only_when_both_layers_agree():
    passed, reason = qc.decide(_verdict(), [])
    assert passed and reason == ""


def test_weak_hook_is_rejected_even_when_the_model_says_pass():
    passed, reason = qc.decide(_verdict(hook_strength=2), [])
    assert not passed
    assert "hook_strength" in reason


def test_templated_is_rejected_even_when_the_model_says_pass():
    passed, reason = qc.decide(_verdict(looks_templated=True), [])
    assert not passed
    assert "same clip" in reason


def test_hard_failure_alone_rejects():
    passed, reason = qc.decide(_verdict(), ["not vertical: 1920x1080"])
    assert not passed
    assert "1920x1080" in reason


def test_identical_frames_hash_identically():
    frames = [_png((10, 20, 30)), _png((200, 200, 200))]
    assert phash.similarity(phash.clip_hash(frames), phash.clip_hash(frames)) == 1.0


def test_different_content_is_less_similar():
    a = phash.clip_hash([_png((0, 0, 0)), _png((255, 255, 255))])
    gradient = Image.linear_gradient("L").convert("RGB")
    buffer = io.BytesIO()
    gradient.save(buffer, format="PNG")
    b = phash.clip_hash([buffer.getvalue(), _png((255, 255, 255))])
    assert phash.similarity(a, b) < 1.0
