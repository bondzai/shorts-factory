import json
import sqlite3

import pytest

from factory import channels, db, logs, mcp

CH = "gravity-lab"


@pytest.fixture
def conn(sandbox):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(db.SCHEMA.read_text())
    channels.create(connection, name="Gravity Lab", channel_id=CH)
    yield connection
    connection.close()


# --- logging -----------------------------------------------------------------

def test_an_event_lands_on_disk_as_json(sandbox):
    logs.event("clip.rendered", channel=CH, clip="abc", duration_s=17.4)
    written = logs.read()
    assert len(written) == 1
    assert written[0]["event"] == "clip.rendered"
    assert written[0]["clip"] == "abc"
    assert written[0]["duration_s"] == 17.4
    assert written[0]["at"].endswith("+00:00") or "T" in written[0]["at"]


def test_newest_first(sandbox):
    logs.event("one")
    logs.event("two")
    assert [r["event"] for r in logs.read()] == ["two", "one"]


def test_filters(sandbox):
    logs.event("clip.qc", channel=CH, clip="a", level="warn")
    logs.event("clip.qc", channel="other", clip="b")
    logs.event("agent.call", channel=CH, clip="a")
    assert len(logs.read(channel=CH)) == 2
    assert len(logs.read(level="warn")) == 1
    assert len(logs.read(event_name="clip.")) == 2
    assert len(logs.read(clip="b")) == 1


def test_limit_is_respected(sandbox):
    for i in range(10):
        logs.event("tick", i=i)
    assert len(logs.read(limit=3)) == 3


def test_a_corrupt_line_does_not_lose_the_file(sandbox):
    logs.event("good.one")
    path = next(logs.log_dir().glob("*.jsonl"))
    with open(path, "a") as handle:
        handle.write("{not json\n")
    logs.event("good.two")
    assert {r["event"] for r in logs.read()} == {"good.one", "good.two"}


def test_logging_never_raises_even_when_the_value_is_odd(sandbox):
    class Odd:
        def __repr__(self):
            return "odd"

    record = logs.event("weird", thing=Odd())
    assert record["event"] == "weird"
    assert logs.read()[0]["thing"] == "odd"


def test_an_unknown_level_falls_back_to_info(sandbox):
    logs.event("x", level="screaming")
    assert logs.read()[0]["level"] == "info"


# --- MCP ---------------------------------------------------------------------

def test_the_server_builds_and_names_itself(sandbox):
    assert mcp.build_server().name == "shorts-factory"


def test_publishing_is_off_unless_asked(sandbox, monkeypatch):
    monkeypatch.delenv(mcp.ALLOW_PUBLISH_ENV, raising=False)
    assert mcp._publishing_allowed() is False
    monkeypatch.setenv(mcp.ALLOW_PUBLISH_ENV, "1")
    assert mcp._publishing_allowed() is True
    monkeypatch.setenv(mcp.ALLOW_PUBLISH_ENV, "no")
    assert mcp._publishing_allowed() is False


def _text(result) -> str:
    return " ".join(
        getattr(block, "text", "") for block in getattr(result, "content", []) or []
    )


@pytest.mark.anyio
async def test_every_tool_is_registered(sandbox):
    names = {tool.name for tool in await mcp.build_server().list_tools()}
    assert {"plan_clips", "build_clips", "review_queue", "approve_clip",
            "publish_approved", "recent_logs"} <= names


@pytest.mark.anyio
async def test_approve_is_refused_by_default(sandbox, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.delenv(mcp.ALLOW_PUBLISH_ENV, raising=False)
    with pytest.raises(ToolError) as excinfo:
        await mcp.build_server().call_tool("approve_clip", {"clip_id": "whatever"})
    # The reason has to survive to the agent, not just to the server log.
    assert "disabled" in str(excinfo.value)
    assert "--allow-publish" in str(excinfo.value)


@pytest.mark.anyio
async def test_a_refusal_is_written_to_the_log(sandbox, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.delenv(mcp.ALLOW_PUBLISH_ENV, raising=False)
    with pytest.raises(ToolError):
        await mcp.build_server().call_tool("publish_approved", {})
    refusals = logs.read(event_name="mcp.refused")
    assert refusals and refusals[0]["tool"] == "publish_approved"


@pytest.mark.anyio
async def test_approving_works_once_the_operator_allows_it(sandbox, monkeypatch):
    monkeypatch.setenv(mcp.ALLOW_PUBLISH_ENV, "1")
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        clip_id = db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race",
            seed=1, params={}, hook="h", plan_why="w",
        )
        db.update(conn, clip_id, status="awaiting_approval")
    await mcp.build_server().call_tool("approve_clip", {"clip_id": clip_id})
    with db.connect() as conn:
        assert db.get(conn, clip_id)["status"] == "approved"


@pytest.mark.anyio
async def test_rejecting_is_allowed_without_the_flag(sandbox, monkeypatch):
    monkeypatch.delenv(mcp.ALLOW_PUBLISH_ENV, raising=False)
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        clip_id = db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race",
            seed=1, params={}, hook="h", plan_why="w",
        )
    await mcp.build_server().call_tool(
        "reject_clip", {"clip_id": clip_id, "reason": "weak hook"}
    )
    with db.connect() as conn:
        assert db.get(conn, clip_id)["status"] == "qc_rejected"


@pytest.mark.anyio
async def test_read_only_tools_work_without_the_flag(sandbox, monkeypatch):
    monkeypatch.delenv(mcp.ALLOW_PUBLISH_ENV, raising=False)
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
    result = await mcp.build_server().call_tool("list_channels", {})
    assert "Gravity Lab" in _text(result)


@pytest.mark.anyio
async def test_every_mcp_call_is_attributed_in_the_log(sandbox):
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
    await mcp.build_server().call_tool("list_channels", {})
    written = logs.read(event_name="mcp.call")
    assert written and written[0]["actor"] == "mcp"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_a_missing_key_is_explained_not_swallowed(sandbox, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr(mcp, "_credentials_missing", lambda: True)
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
    with pytest.raises(ToolError) as excinfo:
        await mcp.build_server().call_tool("plan_clips", {"count": 1})
    message = str(excinfo.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "Nothing was spent" in message


@pytest.mark.anyio
async def test_build_checks_credentials_before_rendering(sandbox, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setattr(mcp, "_credentials_missing", lambda: True)
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
    with pytest.raises(ToolError, match="ANTHROPIC_API_KEY"):
        await mcp.build_server().call_tool("build_clips", {})


# --- the path that needs no credential ---------------------------------------

@pytest.mark.anyio
async def test_the_agent_path_needs_no_credential(sandbox, monkeypatch):
    """render/submit tools must never ask for a key: the caller is the brain."""
    monkeypatch.setattr(mcp, "_credentials_missing", lambda: True)
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        clip_id = db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race",
            seed=1, params={}, hook="h", plan_why="w",
        )
        db.update(
            conn, clip_id, status="rendered", width=1080, height=1920, fps=30.0,
            duration_s=17.0, loudness_lufs=-14.5, sameness=0.2,
        )
    server = mcp.build_server()
    result = await server.call_tool("submit_metadata", {
        "clip_id": clip_id, "title": "Which of these four marbles wins the race?",
        "description": "Seven ramps and no commentary at all.",
        "hashtags": ["#shorts", "#marbles", "#satisfying"],
    })
    assert not result.is_error
    with db.connect() as conn:
        # With QC off the clip waits for `factory qc` instead of an agent's verdict.
        from factory.pipeline.common import qc_enabled
        assert db.get(conn, clip_id)["status"] == ("described" if qc_enabled() else "awaiting_qc")


@pytest.mark.anyio
async def test_a_bad_title_is_refused_with_the_reason(sandbox):
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        clip_id = db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race",
            seed=1, params={}, hook="h", plan_why="w",
        )
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="metadata rejected"):
        await mcp.build_server().call_tool("submit_metadata", {
            "clip_id": clip_id, "title": "too short",
            "description": "Seven ramps and no commentary at all.",
            "hashtags": ["#shorts"],
        })


@pytest.mark.anyio
async def test_the_server_keeps_the_arithmetic(sandbox):
    """An agent insisting a clip is perfect cannot beat a measured failure."""
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        clip_id = db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race",
            seed=1, params={}, hook="h", plan_why="w",
        )
        db.update(
            conn, clip_id, status="described", title="A title long enough to pass",
            hashtags_json='["#shorts"]', width=1080, height=1920, fps=30.0,
            duration_s=17.0, loudness_lufs=-14.5,
            sameness=0.99,  # measured here, not claimed by the caller
        )
    result = await mcp.build_server().call_tool("submit_qc", {
        "clip_id": clip_id, "verdict": "pass", "hook_strength": 5,
        "looks_templated": False, "policy_risk": "low",
        "reasons": ["perfect in every way"],
    })
    assert not result.is_error
    body = " ".join(b.text for b in result.content if getattr(b, "text", None))
    assert "qc_rejected" in body
    assert "too similar" in body


@pytest.mark.anyio
async def test_qc_needs_metadata_first(sandbox):
    from mcp.server.mcpserver.exceptions import ToolError

    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        clip_id = db.insert_clip(
            conn, channel_id=CH, generator="physics", variant="marble_race",
            seed=1, params={}, hook="h", plan_why="w",
        )
        db.update(conn, clip_id, status="rendered", width=1080, height=1920,
                  fps=30.0, duration_s=17.0, loudness_lufs=-14.5, sameness=0.1)
    with pytest.raises(ToolError, match="no title yet"):
        await mcp.build_server().call_tool("submit_qc", {
            "clip_id": clip_id, "verdict": "pass", "hook_strength": 4,
            "looks_templated": False, "policy_risk": "low", "reasons": ["fine"],
        })


@pytest.mark.anyio
async def test_a_channel_cannot_be_asked_for_a_variant_it_disallows(sandbox):
    from mcp.server.mcpserver.exceptions import ToolError

    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH,
                        variants=["physics/funnel_drop"])
    with pytest.raises(ToolError, match="does not allow"):
        await mcp.build_server().call_tool("render_clip", {
            "variant": "marble_race", "channel": CH,
        })


@pytest.mark.anyio
async def test_render_gives_the_agent_something_to_compare_against(sandbox):
    """Asking 'does this repeat the channel' without showing the channel is a
    question with no answer — the agent answered about the genre instead."""
    with db.connect() as conn:
        channels.create(conn, name="Gravity Lab", channel_id=CH)
        for seed in (1, 2):
            clip_id = db.insert_clip(
                conn, channel_id=CH, generator="physics", variant="marble_race",
                seed=seed, params={}, hook="h", plan_why="w",
            )
            db.update(
                conn, clip_id, status="published", title=f"Title {seed}",
                render_desc=f"{seed} marbles race down a stage",
            )
    import json as _json

    result = await mcp.build_server().call_tool(
        "render_clip", {"variant": "marble_race", "channel": CH}
    )
    text = next(b.text for b in result.content if getattr(b, "text", None))
    recent = _json.loads(text)["measured"]["recent_on_this_channel"]
    assert len(recent) == 2
    assert {r["title"] for r in recent} == {"Title 1", "Title 2"}


@pytest.mark.anyio
async def test_the_templated_question_says_what_it_means(sandbox):
    tools = {t.name: t for t in await mcp.build_server().list_tools()}
    text = tools["submit_qc"].description
    assert "THIS channel" in text
    assert "not asking whether the format is common elsewhere" in text.lower()
