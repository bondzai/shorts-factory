"""sysviz makes claims about mathematics, so the tests check the mathematics.

Everything else in the factory can be wrong in a way that costs a clip. A wrong
explanation costs the channel's credibility with the only audience that would
pay a high CPM for it, so these run the arithmetic independently.
"""

import hashlib
import json
import random

import pytest

from factory.generators import sysviz

W, H, FPS = 540, 960, 30


def concept(concept_id):
    for c in sysviz.load_concepts():
        if c.id == concept_id:
            return c
    raise AssertionError(f"no concept {concept_id}")


# --- the library is hand-written and has to stay loadable ---------------------

def test_every_concept_file_parses_and_names_a_real_engine():
    concepts = sysviz.load_concepts()
    assert concepts, "the library is the module; an empty one is a bug"
    for c in concepts:
        assert c.engine in sysviz.ENGINES
        assert c.variant in sysviz.SystemViz.variants


def test_every_row_refers_to_a_slot_the_engine_actually_produces():
    for c in sysviz.load_concepts():
        slots, _ = sysviz.ENGINES[c.engine](random.Random(1), c.spec)
        for row in c.rows:
            assert row["slot"] in slots, f"{c.id}: no slot {row['slot']}"
            if "compare" in row:
                assert row["compare"] in slots, f"{c.id}: no slot {row['compare']}"
        c.claim.format(**slots)  # raises KeyError if the claim names a dead slot


def test_each_variant_has_somewhere_to_get_a_concept_from():
    for variant in sysviz.SystemViz.variants:
        assert sysviz.load_concepts(variant), f"{variant} has no concept file"


def test_a_concept_file_missing_a_key_names_the_file(sandbox, tmp_path, monkeypatch):
    directory = tmp_path / "concepts"
    directory.mkdir()
    (directory / "broken.json").write_text(json.dumps({"id": "x", "variant": "y"}))
    monkeypatch.setattr(sysviz, "concepts_dir", lambda: directory)
    with pytest.raises(ValueError, match="broken.json"):
        sysviz.load_concepts()


def test_asking_for_a_concept_that_is_not_there_names_what_is():
    with pytest.raises(ValueError, match="diffie-hellman"):
        sysviz.SystemViz()._pick_concept(random.Random(1), "key_exchange", "absent")


# --- the arithmetic, checked against an independent computation ---------------

def test_the_avalanche_hashes_are_real_sha256():
    slots, facts = sysviz.sha256_avalanche(random.Random(5), concept("sha256-avalanche").spec)
    assert slots["hash_a"] == hashlib.sha256(slots["input_a"].encode()).hexdigest()
    assert slots["hash_b"] == hashlib.sha256(slots["input_b"].encode()).hexdigest()


def test_exactly_one_character_differs_because_the_label_says_so():
    """The row is labelled "one letter changed". That has to be true."""
    for seed in range(40):
        slots, _ = sysviz.sha256_avalanche(random.Random(seed), concept("sha256-avalanche").spec)
        a, b = slots["input_a"], slots["input_b"]
        assert len(a) == len(b)
        assert sum(1 for x, y in zip(a, b) if x != y) == 1


def test_the_bit_count_on_screen_is_the_bit_count():
    for seed in range(20):
        slots, facts = sysviz.sha256_avalanche(
            random.Random(seed), concept("sha256-avalanche").spec
        )
        expected = bin(int(slots["hash_a"], 16) ^ int(slots["hash_b"], 16)).count("1")
        assert facts["bits_changed"] == expected
        assert slots["bits"] == f"{expected} of 256"


def test_the_avalanche_is_worth_a_clip_at_all():
    """Around half of 256 bits should move. Far off that would mean a bug."""
    counts = [
        sysviz.sha256_avalanche(random.Random(s), concept("sha256-avalanche").spec)[1][
            "bits_changed"
        ]
        for s in range(60)
    ]
    assert 100 < sum(counts) / len(counts) < 156


def test_both_sides_of_the_key_exchange_reach_the_same_number():
    for seed in range(40):
        slots, facts = sysviz.diffie_hellman(random.Random(seed), concept("diffie-hellman").spec)
        assert slots["shared_a"] == slots["shared_b"]
        assert facts["shared"] == pow(facts["g"], facts["a"] * facts["b"], facts["p"])


def test_the_published_primes_are_prime_and_g_generates_the_whole_group():
    """A small p with a low-order g would make the clip a lie by omission."""
    def is_prime(n):
        return n > 1 and all(n % d for d in range(2, int(n**0.5) + 1))

    for p, g in concept("diffie-hellman").spec["primes"]:
        assert is_prime(p), p
        assert is_prime((p - 1) // 2), f"{p} is not a safe prime"
        order = next(k for k in range(1, p) if pow(g, k, p) == 1)
        assert order == p - 1, f"g={g} has order {order} mod {p}"


def test_the_merkle_root_is_the_tree_it_claims_to_be():
    slots, facts = sysviz.merkle_root(random.Random(9), concept("merkle-root").spec)
    def node(text):
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    leaves = slots["leaves"].split(" ")
    level0 = [node(r) for r in leaves]
    assert slots["level0"] == "".join(level0)
    level1 = [node(level0[0] + level0[1]), node(level0[2] + level0[3])]
    assert slots["level1"] == "".join(level1)
    assert slots["root"] == node(level1[0] + level1[1])


def test_editing_one_record_is_editing_exactly_one_record():
    for seed in range(30):
        slots, facts = sysviz.merkle_root(random.Random(seed), concept("merkle-root").spec)
        before = slots["leaves"].split(" ")
        after = slots["leaves_b"].split(" ")
        assert sum(1 for x, y in zip(before, after) if x != y) == 1
        assert slots["root"] != slots["root_b"]


# --- layout, reveal and sound -------------------------------------------------

def test_a_concept_that_cannot_fit_is_refused_rather_than_clipped():
    wide = sysviz.Concept(
        id="too-wide", variant="hash_avalanche", engine="sha256_avalanche",
        headline="x", footer="", claim="x",
        rows=[{"label": "l", "slot": "v"}],
    )
    with pytest.raises(ValueError, match="does not fit"):
        sysviz._layout(wide, {"v": "x" * 400}, W, H)


def test_the_screen_is_laid_out_once_so_nothing_moves_while_it_fills():
    c = concept("sha256-avalanche")
    slots, _ = sysviz.ENGINES[c.engine](random.Random(3), c.spec)
    blocks, *_ = sysviz._layout(c, slots, W, H)
    ys = [line.y for block in blocks for line in block.lines]
    assert ys == sorted(ys)
    assert all(0 < y < H for y in ys)


def test_typing_starts_almost_immediately(sandbox):
    """76% of viewers swipe away in the feed. A static title card is why."""
    c = concept("sha256-avalanche")
    slots, _ = sysviz.ENGINES[c.engine](random.Random(3), c.spec)
    blocks, *_ = sysviz._layout(c, slots, W, H)
    reveal, _ = sysviz.SystemViz()._script(blocks, 15 * FPS, FPS)
    assert any(reveal[FPS // 2]), "nothing on screen half a second in"


def test_the_reveal_only_ever_moves_forward(sandbox):
    c = concept("merkle-root")
    slots, _ = sysviz.ENGINES[c.engine](random.Random(3), c.spec)
    blocks, *_ = sysviz._layout(c, slots, W, H)
    reveal, _ = sysviz.SystemViz()._script(blocks, 10 * FPS, FPS)
    for earlier, later in zip(reveal, reveal[1:]):
        assert all(b >= a for a, b in zip(earlier, later))
    assert reveal[-1] == [len(line.text) for block in blocks for line in block.lines]


def test_every_character_makes_a_sound_and_none_land_past_the_end(sandbox):
    c = concept("sha256-avalanche")
    slots, _ = sysviz.ENGINES[c.engine](random.Random(3), c.spec)
    blocks, *_ = sysviz._layout(c, slots, W, H)
    reveal, impacts = sysviz.SystemViz()._script(blocks, 15 * FPS, FPS)
    characters = sum(len(line.text) for block in blocks for line in block.lines)
    assert len(impacts) == -(-characters // sysviz.CHARS_PER_IMPACT)
    assert all(0 <= i.t < 15 for i in impacts)


def test_frames_are_the_right_size_and_count(sandbox):
    c = concept("diffie-hellman")
    slots, _ = sysviz.ENGINES[c.engine](random.Random(3), c.spec)
    layout = sysviz._layout(c, slots, W, H)
    reveal, _ = sysviz.SystemViz()._script(layout[0], 2 * FPS, FPS)
    frames = list(sysviz.SystemViz()._frames(c, layout, reveal, W, H))
    assert len(frames) == 2 * FPS
    assert all(len(f) == W * H * 3 for f in frames)


def test_the_seed_fixes_the_clip(sandbox):
    c = concept("sha256-avalanche")
    a, _ = sysviz.ENGINES[c.engine](random.Random(77), c.spec)
    b, _ = sysviz.ENGINES[c.engine](random.Random(77), c.spec)
    assert a == b


def test_different_seeds_give_different_clips(sandbox):
    c = concept("sha256-avalanche")
    a, _ = sysviz.ENGINES[c.engine](random.Random(77), c.spec)
    b, _ = sysviz.ENGINES[c.engine](random.Random(78), c.spec)
    assert a != b


def test_it_is_registered_and_ready(sandbox):
    from factory import generators

    assert generators.all_generators()["sysviz"].ready is True
    assert "sysviz" in generators.available(None)


def test_consensus_round_is_gone_on_purpose():
    """Kept as a test so nobody adds it back without reading why it went."""
    assert "consensus_round" not in sysviz.SystemViz.variants
    assert "consensus" in sysviz.__doc__.lower()
