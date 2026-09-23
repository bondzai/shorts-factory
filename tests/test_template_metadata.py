"""The template writes what the rules already fix, and is held to the same
gates as an agent: bounds, the spoiler check, the whole lineup or none."""

from io import BytesIO

import pytest
from PIL import Image

from factory import llm, pipeline
from factory.agents import template
from factory.models import Metadata

FACTS = {
    "variant": "marble_race", "seed": 7, "stage": "plinko",
    "lineup": ["red", "blue", "violet", "amber", "green"],
    "stage_words": "a band of pegs, then a four-armed wheel, then a band of pegs with 2 spinning bars",
    "rounds": [{"stage": "plinko", "winner": "green", "finishes": {"green": 10.4, "red": 11.5}}],
    "winner": "green", "finishes": {"green": 10.4, "red": 11.5}, "runner_up": "red", "margin_s": 1.04,
}


def test_the_title_leads_with_the_pick_and_names_the_whole_field_in_screen_order():
    meta, cost = template.write_metadata(facts=FACTS, seed=0)
    assert cost == 0.0
    # No colour list in the title: the feed cuts at 45 and the marbles are on
    # screen under it. The count and the stage carry the pick; the pinned
    # comment carries the colours, where the viewer answers with one.
    assert meta.title == "Pick one — five go down the plinko"
    assert len(meta.title) <= template.FEED_MAX == 45
    assert not any(c in meta.title for c in FACTS["lineup"])
    assert meta.comment_prompt == "Red, blue, violet, amber or green — which did you back?"
    assert meta.hook_text is None  # the render's caption bank already chose


def test_it_passes_the_pipeline_s_own_spoiler_gate(sandbox):
    meta, _ = template.write_metadata(facts=FACTS, seed=3)
    first = meta.description.split(". ")[0]
    assert pipeline.spoiler(FACTS, title=meta.title, comment_prompt=meta.comment_prompt, description=first) is None
    assert "green" not in first and "first" not in first.lower().replace("first bend", "")


def test_the_shape_rotates_by_seed_so_consecutive_clips_differ():
    titles = {template.write_metadata(facts=FACTS, seed=s)[0].title for s in range(len(template.SHAPES))}
    assert len(titles) == len(template.SHAPES)
    assert all(len(t) <= template.FEED_MAX for t in titles)


def test_a_long_stage_name_still_fits_the_feed():
    facts = {**FACTS, "lineup": ["red", "blue", "violet", "amber", "green", "white", "black"], "stage": "switchback",
             "rounds": [{"stage": "switchback", "winner": "green", "finishes": {"green": 10.4}}]}
    for seed in range(len(template.SHAPES)):
        meta, _ = template.write_metadata(facts=facts, seed=seed)
        assert len(meta.title) <= template.FEED_MAX and "switchback" in meta.title


def test_every_field_is_inside_the_bounds_an_agent_is_held_to():
    for seed in range(5):
        meta, _ = template.write_metadata(facts=FACTS, seed=seed)
        Metadata.model_validate(meta.model_dump())  # raises if out of bounds
        assert 3 <= len(meta.hashtags) <= 5 and meta.hashtags[0] == "#shorts"


def test_it_declines_anything_but_a_marble_race():
    assert not template.can_write({"variant": "funnel_drop"})
    with pytest.raises(template.Unsupported):
        template.write_metadata(facts={"variant": "ball_battle", "lineup": ["a"]}, seed=1)


def test_frames_are_shrunk_before_any_brain_sees_them(sandbox):
    big = BytesIO()
    Image.new("RGB", (1080, 1920), (16, 26, 22)).save(big, format="PNG")
    small = llm.shrink(big.getvalue(), 512)
    with Image.open(BytesIO(small)) as im:
        assert im.size == (288, 512)
    assert len(small) < len(big.getvalue())
    tiny = BytesIO(); Image.new("RGB", (100, 200)).save(tiny, format="PNG")
    assert llm.shrink(tiny.getvalue(), 512) == tiny.getvalue()  # never upscaled


def test_a_shape_already_on_the_channel_is_passed_over():
    """Two four-marble races on the spillway landed on the same seed slot and
    shipped the same title twice, which reads as a re-upload."""
    first = template.title(FACTS, seed=0)
    assert template.title(FACTS, seed=0, taken={first}) != first
    assert template.title(FACTS, seed=0, taken={first}) == template.title(FACTS, seed=1)
