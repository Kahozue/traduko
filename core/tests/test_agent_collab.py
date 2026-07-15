import pytest

from traduko.agents.collab import AgentSession, Blackboard, CollabError, MessageChannel


def test_session_defaults() -> None:
    session = AgentSession(id="a1", name="proofreader")
    assert session.tools == [] and session.budget_usd is None


def test_blackboard_read_write_snapshot() -> None:
    board = Blackboard()
    assert board.read("missing") is None
    board.write("issues", [1, 2])
    assert board.read("issues") == [1, 2]
    assert board.keys() == ["issues"]
    snap = board.snapshot()
    board.write("issues", [])
    assert snap == {"issues": [1, 2]}


def test_channel_point_to_point() -> None:
    channel = MessageChannel()
    channel.register("a")
    channel.register("b")
    channel.send("a", "b", {"kind": "task", "payload": 1})
    assert channel.receive("b") == [{"from": "a", "body": {"kind": "task", "payload": 1}}]
    assert channel.receive("b") == []


def test_channel_broadcast_skips_sender() -> None:
    channel = MessageChannel()
    for agent_id in ("a", "b", "c"):
        channel.register(agent_id)
    channel.broadcast("a", {"kind": "note"})
    assert channel.receive("a") == []
    assert len(channel.receive("b")) == 1
    assert len(channel.receive("c")) == 1


def test_channel_unknown_agent() -> None:
    channel = MessageChannel()
    channel.register("a")
    with pytest.raises(CollabError):
        channel.send("a", "ghost", {})
    with pytest.raises(CollabError):
        channel.receive("ghost")
