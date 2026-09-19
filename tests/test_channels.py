import sqlite3

import pytest

from factory import channels, db


@pytest.fixture
def conn(sandbox):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA.read_text())
    yield connection
    connection.close()


def test_id_comes_from_the_name(conn):
    channel = channels.create(conn, name="Gravity Lab")
    assert channel.id == "gravity-lab"
    assert channel.active is True


def test_duplicate_ids_are_refused(conn):
    channels.create(conn, name="Gravity Lab")
    with pytest.raises(ValueError):
        channels.create(conn, name="Gravity Lab")


def test_each_channel_gets_its_own_rules_file(conn):
    a = channels.create(conn, name="Gravity Lab")
    b = channels.create(conn, name="HODL Tales")
    assert a.rules_path != b.rules_path
    assert a.rules_path.exists() and b.rules_path.exists()
    assert "Gravity Lab" in a.rules()
    assert "HODL Tales" in b.rules()


def test_rules_seed_from_the_legacy_file_for_the_first_channel(conn, sandbox):
    (sandbox / "rules.md").write_text("# carried over\n")
    main = channels.create(conn, name="Main", channel_id=channels.DEFAULT_ID)
    assert main.rules() == "# carried over\n"


def test_tokens_are_never_shared(conn):
    a = channels.create(conn, name="Gravity Lab")
    b = channels.create(conn, name="HODL Tales")
    assert a.token_path != b.token_path


def test_variants_gate_what_a_channel_may_make(conn):
    channel = channels.create(conn, name="Gravity Lab", variants=["physics/marble_race"])
    assert channel.allows("physics", "marble_race")
    assert not channel.allows("physics", "funnel_drop")


def test_an_empty_variant_list_allows_anything_ready(conn):
    channel = channels.create(conn, name="Gravity Lab")
    assert channel.allows("physics", "funnel_drop")
    assert channel.allows("anything", "at_all")


def test_edit_changes_fields_and_keeps_the_id(conn):
    channels.create(conn, name="Soul Founder", channel_id="soul")
    edited = channels.edit(conn, "soul", name="Gravity Lab", handle="@gravitylabii")
    assert edited.id == "soul"
    assert edited.name == "Gravity Lab"
    assert edited.handle == "@gravitylabii"


def test_edit_refuses_unknown_fields(conn):
    channels.create(conn, name="Gravity Lab")
    with pytest.raises(ValueError):
        channels.edit(conn, "gravity-lab", nonsense=1)


def test_resolve_picks_the_only_active_channel(conn):
    channels.create(conn, name="Gravity Lab")
    assert channels.resolve(conn, None).id == "gravity-lab"


def test_resolve_asks_when_several_are_active(conn):
    channels.create(conn, name="Gravity Lab")
    channels.create(conn, name="HODL Tales")
    with pytest.raises(ValueError, match="pass --channel"):
        channels.resolve(conn, None)


def test_a_paused_channel_does_not_count_as_a_choice(conn):
    channels.create(conn, name="Gravity Lab")
    channels.create(conn, name="HODL Tales")
    channels.edit(conn, "hodl-tales", active=0)
    assert channels.resolve(conn, None).id == "gravity-lab"


def test_resolve_names_what_exists_when_the_id_is_wrong(conn):
    channels.create(conn, name="Gravity Lab")
    with pytest.raises(KeyError, match="gravity-lab"):
        channels.resolve(conn, "nope")
