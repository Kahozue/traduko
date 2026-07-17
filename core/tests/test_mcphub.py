import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from traduko.agents.tools import ToolError
from traduko.config import McpServerConfig
from traduko.mcphub import (
    MCPManager,
    active_tools,
    set_active,
)


class FakeSession:
    """Mimics the slice of mcp.ClientSession the manager touches."""

    def __init__(self, tools: list[SimpleNamespace], results: dict[str, object]):
        self._tools = tools
        self._results = results
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self) -> None:
        pass

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        outcome = self._results[name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


ECHO_TOOL = SimpleNamespace(
    name="echo",
    description="Echo the text back.",
    inputSchema={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "text to echo"}},
        "required": ["text"],
    },
)


def text_result(text: str):
    return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])


def make_connector(sessions: dict[str, object]):
    @asynccontextmanager
    async def connector(config: McpServerConfig):
        session = sessions[config.command or config.url]
        if isinstance(session, Exception):
            raise session
        yield session

    return connector


def run_manager(manager: MCPManager):
    """Run the manager's loop in a background thread, mirroring the service."""
    loop = asyncio.new_event_loop()
    started = threading.Event()

    def runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(manager.start())
        started.set()
        loop.run_forever()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    started.wait(timeout=5)

    def shutdown() -> None:
        asyncio.run_coroutine_threadsafe(manager.stop(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)

    return shutdown


def wait_for(predicate, timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")


def test_manager_connects_and_snapshots_tools() -> None:
    session = FakeSession([ECHO_TOOL], {"echo": text_result("echo:hi")})
    manager = MCPManager(
        {"demo": McpServerConfig(command="demo-cmd", enabled=True)},
        connector=make_connector({"demo-cmd": session}),
    )
    shutdown = run_manager(manager)
    try:
        wait_for(lambda: manager.status()[0]["state"] == "connected")
        status = manager.status()[0]
        assert status["name"] == "demo"
        assert status["tools"] == ["echo"]
        assert status["error"] == ""
    finally:
        shutdown()


def test_agent_tools_wrap_namespace_and_bridge_from_worker_thread() -> None:
    session = FakeSession([ECHO_TOOL], {"echo": text_result("echo:hi")})
    manager = MCPManager(
        {"demo": McpServerConfig(command="demo-cmd", enabled=True)},
        connector=make_connector({"demo-cmd": session}),
    )
    shutdown = run_manager(manager)
    try:
        wait_for(lambda: manager.status()[0]["state"] == "connected")
        tools = manager.agent_tools()
        assert [tool.name for tool in tools] == ["demo.echo"]
        assert tools[0].parameters == {
            "text": {"type": "string", "required": True, "description": "text to echo"}
        }
        # The test runs in the main thread while the loop runs in the
        # background thread — exactly the worker-thread bridge in production.
        assert tools[0].handler({"text": "hi"}) == "echo:hi"
        assert session.calls == [("echo", {"text": "hi"})]
    finally:
        shutdown()


def test_tool_error_result_raises_tool_error() -> None:
    bad = SimpleNamespace(isError=True, content=[SimpleNamespace(text="boom")])
    session = FakeSession([ECHO_TOOL], {"echo": bad})
    manager = MCPManager(
        {"demo": McpServerConfig(command="demo-cmd", enabled=True)},
        connector=make_connector({"demo-cmd": session}),
    )
    shutdown = run_manager(manager)
    try:
        wait_for(lambda: manager.status()[0]["state"] == "connected")
        with pytest.raises(ToolError, match="boom"):
            manager.call_tool("demo", "echo", {"text": "hi"})
    finally:
        shutdown()


def test_failing_server_degrades_without_touching_others() -> None:
    session = FakeSession([ECHO_TOOL], {"echo": text_result("echo:hi")})
    manager = MCPManager(
        {
            "good": McpServerConfig(command="good-cmd", enabled=True),
            "bad": McpServerConfig(command="bad-cmd", enabled=True),
        },
        connector=make_connector(
            {"good-cmd": session, "bad-cmd": RuntimeError("cannot spawn")}
        ),
        retry_delay=30.0,
    )
    shutdown = run_manager(manager)
    try:
        wait_for(
            lambda: {row["name"]: row["state"] for row in manager.status()}
            == {"good": "connected", "bad": "error"}
        )
        rows = {row["name"]: row for row in manager.status()}
        assert "cannot spawn" in rows["bad"]["error"]
        assert rows["bad"]["tools"] == []
        assert [tool.name for tool in manager.agent_tools()] == ["good.echo"]
        with pytest.raises(ToolError, match="is error"):
            manager.call_tool("bad", "echo", {})
    finally:
        shutdown()


def test_disabled_server_gets_no_supervisor() -> None:
    manager = MCPManager(
        {"off": McpServerConfig(command="off-cmd", enabled=False)},
        connector=make_connector({}),
    )
    shutdown = run_manager(manager)
    try:
        assert manager.status() == [
            {
                "name": "off",
                "transport": "stdio",
                "enabled": False,
                "state": "disabled",
                "error": "",
                "tools": [],
            }
        ]
        assert manager.agent_tools() == []
    finally:
        shutdown()


def test_active_registry_defaults_to_empty() -> None:
    set_active(None)
    assert active_tools() == []
