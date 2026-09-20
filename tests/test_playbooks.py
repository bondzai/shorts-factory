"""A playbook that renders stale facts is worse than no playbook.

The whole reason the prose lives in a file and the numbers come from the
database is that a prompt pasted from last session quietly goes out of date. So
what is tested here is the substitution, not the wording.
"""

import pytest

from factory import channels, db, playbooks


@pytest.fixture(autouse=True)
def channel(sandbox):
    """A playbook always renders against a channel, so give every test one."""
    with db.connect() as conn:
        db.migrate(conn)
        channels.create(conn, name="Gravity Lab", channel_id="main")
        conn.commit()
    return "main"


def test_every_shipped_playbook_renders(sandbox):
    assert playbooks.available(), "the prompts directory is empty"
    for name in playbooks.available():
        text = playbooks.render(name)
        assert text.strip()
        assert "{" not in text.replace("{{", "").replace("}}", ""), (
            f"{name} left a placeholder unfilled"
        )


def test_a_playbook_naming_an_unknown_fact_says_which(sandbox, tmp_path, monkeypatch):
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "bad.md").write_text("Channel {channel}, nonsense {not_a_fact}.")
    monkeypatch.setattr(playbooks, "prompts_dir", lambda: directory)
    with pytest.raises(ValueError, match="not_a_fact"):
        playbooks.render("bad")


def test_asking_for_a_playbook_that_is_not_there_names_what_is(sandbox):
    with pytest.raises(ValueError, match="make-clip"):
        playbooks.render("absent")


def test_the_gates_in_the_prompt_are_the_gates_in_the_config(sandbox):
    from factory import settings

    qc = settings.load().raw["qc"]
    text = playbooks.render("make-clip")
    assert str(qc["max_sameness"]) in text
    assert str(qc["min_seconds"]) in text


def make_clip(conn, **fields):
    clip_id = db.insert_clip(
        conn, channel_id="main", generator="physics", variant="marble_race",
        seed=5, params={}, hook="a hook", plan_why="a reason",
    )
    if fields:
        db.update(conn, clip_id, **fields)
    return clip_id


def test_recent_clips_reach_the_prompt(sandbox):
    with db.connect() as conn:
        make_clip(conn, status="published", title="A title")
    text = playbooks.render("make-clip", "main")
    assert "A title" in text
    assert "marble_race" in text


def test_an_empty_channel_says_so_rather_than_implying_history(sandbox):
    text = playbooks.render("make-clip", "main")
    assert "Nothing made on this channel yet." in text


def test_advice_from_metrics_is_absent_until_there_are_metrics(sandbox):
    """Without n, the retention advice is a guess, and the prompt has to say so."""
    text = playbooks.render("make-clip", "main")
    assert "nothing below is evidence" in text

    with db.connect() as conn:
        make_clip(conn, status="published", title="Measured", views=715,
                  avg_view_pct=76.2)
    text = playbooks.render("make-clip", "main")
    assert "nothing below is evidence" not in text
    assert "715 views" in text
    assert "n = 1" in text


def test_the_prompt_only_offers_modules_the_channel_allows(sandbox):
    from factory import channels

    with db.connect() as conn:
        channels.edit(conn, "main", variants=["physics/marble_race"])
    text = playbooks.render("make-clip", "main")
    assert "marble_race" in text
    assert "market_replay" not in text


def test_the_mcp_tool_and_the_cli_serve_the_same_text(sandbox):
    assert "make-clip" in playbooks.available()
    assert playbooks.render("make-clip") == playbooks.render("make-clip", None)


def test_a_rejected_clip_carries_its_reason_into_the_prompt(sandbox):
    """Codex, asked to plan a week, correctly refused to re-run a rejected
    variant "until the rejection's cause has been addressed" — and then had no
    way to know the cause, because the prompt listed the status without the
    reason. Only the measured clause is passed on; reviewer prose stays out."""
    with db.connect() as conn:
        make_clip(
            conn, status="qc_rejected", title="Jammed",
            reject_reason="too similar to an existing clip: 0.91 > 0.88; felt samey",
        )
    text = playbooks.render("plan-week", "main")
    assert "rejected: too similar to an existing clip: 0.91 > 0.88" in text
    assert "felt samey" not in text


def test_the_market_brief_rides_on_every_playbook_and_is_not_a_playbook(sandbox):
    assert "market-us" not in playbooks.available()
    assert "us" in playbooks.markets()
    text = playbooks.render("retitle", "main")
    assert "Market: United States" in text and "American English" in text
    with db.connect() as conn:
        db.set_override(conn, "market", "main", "")
    assert "Market: United States" not in playbooks.render("retitle", "main")
