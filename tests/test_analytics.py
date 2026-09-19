import json
import sqlite3

import pytest

from factory import analytics, channels, db

CH = "gravity-lab"


@pytest.fixture
def conn(sandbox):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA.read_text())
    channels.create(connection, name="Gravity Lab", channel_id=CH)
    yield connection
    connection.close()


def publish(conn, *, seed, variant="marble_race", views=None, retained=None,
            hook=None, swipe=None, channel_id=CH, when="2099-01-01T00:00:00+00:00"):
    clip_id = db.insert_clip(
        conn, channel_id=channel_id, generator="physics", variant=variant,
        seed=seed, params={}, hook="rolling", plan_why="t",
    )
    fields = {"status": "published", "published_at": when}
    if views is not None:
        fields |= {"views": views, "avg_view_pct": retained, "swipe_away_pct": swipe}
    if hook is not None:
        fields["qc_json"] = json.dumps({"hook_strength": hook})
    db.update(conn, clip_id, **fields)
    return clip_id


def test_empty_channel_reports_zeroes(conn):
    out = analytics.summary(conn, CH)
    assert out["n_with_metrics"] == 0
    assert out["by_variant"] == []
    assert out["best"] is None


def test_clips_without_metrics_are_not_counted(conn):
    publish(conn, seed=1)
    assert analytics.summary(conn, CH)["n_with_metrics"] == 0


def test_totals_and_best(conn):
    publish(conn, seed=1, views=100, retained=60.0, swipe=30.0)
    publish(conn, seed=2, views=900, retained=80.0, swipe=18.0)
    out = analytics.summary(conn, CH)
    assert out["views_90d"] == 1000
    assert out["retained_median"] == 70.0
    assert out["best"]["views"] == 900


def test_grouping_carries_n_and_sorts_by_retention(conn):
    publish(conn, seed=1, variant="marble_race", views=10, retained=50.0)
    publish(conn, seed=2, variant="marble_race", views=20, retained=60.0)
    publish(conn, seed=3, variant="funnel_drop", views=30, retained=90.0)
    groups = analytics.summary(conn, CH)["by_variant"]
    assert [g["key"] for g in groups] == ["funnel_drop", "marble_race"]
    assert {g["key"]: g["n"] for g in groups} == {"funnel_drop": 1, "marble_race": 2}
    assert groups[1]["retained_median"] == 55.0


def test_hook_buckets_come_from_the_qc_verdict(conn):
    publish(conn, seed=1, views=10, retained=55.0, hook=3)
    publish(conn, seed=2, views=10, retained=75.0, hook=5)
    publish(conn, seed=3, views=10, retained=65.0)  # no verdict at all
    hooks = analytics.summary(conn, CH)["by_hook"]
    assert {g["key"] for g in hooks} == {3, 5}


def test_the_hook_column_states_its_own_bias(conn):
    publish(conn, seed=1, views=10, retained=55.0, hook=4)
    assert "by construction" in analytics.summary(conn, CH)["by_hook_caveat"]


def test_gates_are_reported_as_progress(conn):
    publish(conn, seed=1, views=300_000, retained=70.0)
    out = analytics.summary(conn, CH)
    assert out["gate_tier1_pct"] == 10.0
    assert out["gate_tier2_pct"] == 3.0


def test_another_channel_is_invisible(conn):
    channels.create(conn, name="HODL Tales", channel_id="hodl")
    publish(conn, seed=1, views=100, retained=60.0)
    publish(conn, seed=2, views=9999, retained=99.0, channel_id="hodl")
    assert analytics.summary(conn, CH)["views_90d"] == 100


def test_old_clips_fall_out_of_the_ninety_day_window(conn):
    publish(conn, seed=1, views=500, retained=70.0, when="2020-01-01T00:00:00+00:00")
    out = analytics.summary(conn, CH)
    assert out["n_with_metrics"] == 1
    assert out["views_90d"] == 0


def test_cost_rolls_up_per_agent_and_model(sandbox):
    from factory import analytics as a, logs

    logs.event("agent.call", agent="qc", model="claude-haiku-4-5",
               cost_usd=0.001, input_tokens=100, output_tokens=20)
    logs.event("agent.call", agent="qc", model="claude-haiku-4-5",
               cost_usd=0.002, input_tokens=200, output_tokens=30)
    logs.event("agent.call", agent="analyst", model="claude-opus-5",
               cost_usd=0.05, input_tokens=9000, output_tokens=900)
    rows = a.cost_by_agent()
    assert [r["agent"] for r in rows] == ["analyst", "qc"]
    qc = next(r for r in rows if r["agent"] == "qc")
    assert qc["calls"] == 2
    assert qc["cost_usd"] == pytest.approx(0.003)
    assert qc["input_tokens"] == 300


def test_an_unpriced_model_is_flagged_as_an_estimate(sandbox):
    from factory import analytics as a, logs

    logs.event("agent.call", agent="idea", model="something-new",
               cost_usd=0.01, cost_estimated=True)
    assert a.cost_by_agent()[0]["estimated"] is True


def test_per_agent_models_come_from_config(sandbox):
    from factory import llm

    assert llm.model_for("qc")
    assert llm.model_for(None) == llm.model_for("no-such-agent")
    assert llm.price_of("claude-haiku-4-5") == (1.0, 5.0)
    assert llm.price_of("totally-unknown") == llm.price_of("default")
