import pytest

from factory import generators


def test_physics_is_ready_and_stubs_are_not():
    all_gens = generators.all_generators()
    assert set(all_gens) == {"physics", "market_replay", "sysviz"}
    assert all_gens["physics"].ready is True
    assert all_gens["market_replay"].ready is False
    assert all_gens["sysviz"].ready is False


def test_catalogue_hides_stubs():
    text = generators.catalogue()
    assert "physics" in text
    assert "market_replay" not in text
    assert "sysviz" not in text


def test_ready_generators_is_the_idea_agents_menu():
    assert set(generators.ready_generators()) == {"physics"}


def test_get_unknown_names_what_exists():
    with pytest.raises(KeyError) as excinfo:
        generators.get("nope")
    assert "physics" in str(excinfo.value)


def test_physics_rejects_unknown_variant(tmp_path):
    with pytest.raises(ValueError):
        generators.get("physics").generate(
            seed=1, variant="not_a_variant", params={}, work_dir=tmp_path
        )
