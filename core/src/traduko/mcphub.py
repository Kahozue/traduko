"""MCP client mounting: external tool servers for agent runs.

One supervisor task per enabled server owns the connection and session
for their whole lifetime — the MCP SDK's anyio cancel scopes require the
session context to enter and exit inside the same task. Tool calls from
worker threads (stages run synchronously) are bridged into the
supervisor's queue via run_coroutine_threadsafe. A dead server only
degrades its own tool group: status flips to error, tools empty, and the
supervisor retries with a delay.

The service registers its manager through set_active(); stage code asks
active_tools() and gets an empty list under the CLI where no manager
runs.

Confirmation gate: an enabled but unconfirmed server still connects and
lists its tools — status() carries the names and descriptions the UI
confirmation card shows — but agent_tools() skips it until the user
confirms, so unvetted tool descriptions never reach an agent prompt.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from .agents.tools import AgentTool, ToolError
from .config import McpServerConfig

CALL_TIMEOUT_SECONDS = 60.0


@dataclass
class _ToolInfo:
    name: str
    description: str
    parameters: dict[str, dict]


@dataclass
class _ServerState:
    config: McpServerConfig
    state: str = "connecting"  # connected | connecting | error | disabled
    error: str = ""
    tools: list[_ToolInfo] = field(default_factory=list)
    queue: asyncio.Queue | None = None
    task: asyncio.Task | None = None


@asynccontextmanager
async def default_connector(config: McpServerConfig):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.client.streamable_http import streamablehttp_client

    if config.transport == "stdio":
        params = StdioServerParameters(
            command=config.command, args=config.args, env=config.env or None
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                yield session
    else:
        headers = (
            {"Authorization": f"Bearer {config.auth_token}"}
            if config.auth_token
            else None
        )
        async with streamablehttp_client(config.url, headers=headers) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                yield session


def _parameters_from_schema(schema: dict | None) -> dict[str, dict]:
    if not isinstance(schema, dict):
        return {}
    required = set(schema.get("required") or [])
    parameters: dict[str, dict] = {}
    for name, prop in (schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            prop = {}
        parameters[name] = {
            "type": prop.get("type", "string"),
            "required": name in required,
            "description": prop.get("description", ""),
        }
    return parameters


def _result_text(result) -> str:
    parts = [
        part.text
        for part in getattr(result, "content", [])
        if getattr(part, "text", None) is not None
    ]
    return "\n".join(parts)


class MCPManager:
    def __init__(
        self,
        servers: dict[str, McpServerConfig],
        connector: Callable | None = None,
        retry_delay: float = 5.0,
    ) -> None:
        # Resolved at call time so tests can monkeypatch default_connector.
        self._connector = connector if connector is not None else default_connector
        self._retry_delay = retry_delay
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False
        self._lock = threading.Lock()
        self._servers: dict[str, _ServerState] = {
            name: _ServerState(
                config=config, state="connecting" if config.enabled else "disabled"
            )
            for name, config in servers.items()
        }

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        for name, server in self._servers.items():
            if not server.config.enabled:
                continue
            server.queue = asyncio.Queue()
            server.task = asyncio.create_task(self._supervise(name, server))

    async def stop(self) -> None:
        self._stopping = True
        for server in reversed(list(self._servers.values())):
            if server.task is not None:
                server.task.cancel()
                try:
                    await server.task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _supervise(self, name: str, server: _ServerState) -> None:
        while not self._stopping:
            self._set(server, "connecting", "")
            try:
                async with self._connector(server.config) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    tools = [
                        _ToolInfo(
                            name=tool.name,
                            description=tool.description or "",
                            parameters=_parameters_from_schema(
                                getattr(tool, "inputSchema", None)
                            ),
                        )
                        for tool in listing.tools
                    ]
                    with self._lock:
                        server.tools = tools
                    self._set(server, "connected", "")
                    await self._serve_queue(server, session)
                    return
            except asyncio.CancelledError:
                self._set(server, "disabled", "")
                raise
            except Exception as error:
                with self._lock:
                    server.tools = []
                self._set(server, "error", str(error))
                await asyncio.sleep(self._retry_delay)

    async def _serve_queue(self, server: _ServerState, session) -> None:
        assert server.queue is not None
        while True:
            tool, arguments, future = await server.queue.get()
            try:
                result = await session.call_tool(tool, arguments)
                if getattr(result, "isError", False):
                    raise ToolError(f"{tool}: {_result_text(result)}")
                outcome: object = _result_text(result)
            except ToolError as error:
                outcome = error
            except Exception as error:
                # Connection died mid-call: fail the caller immediately and
                # let the supervisor loop reconnect.
                future.set_result(ToolError(f"{tool}: {error}"))
                raise
            future.set_result(outcome)

    def _set(self, server: _ServerState, state: str, error: str) -> None:
        with self._lock:
            server.state = state
            server.error = error

    def status(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "name": name,
                    "transport": server.config.transport,
                    "enabled": server.config.enabled,
                    "confirmed": server.config.confirmed,
                    "state": server.state,
                    "error": server.error,
                    "tools": [
                        {"name": tool.name, "description": tool.description}
                        for tool in server.tools
                    ],
                }
                for name, server in self._servers.items()
            ]

    def call_tool(
        self,
        server_name: str,
        tool: str,
        arguments: dict,
        timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> str:
        server = self._servers.get(server_name)
        if server is None or server.queue is None or self._loop is None:
            raise ToolError(f"mcp server not available: {server_name}")
        with self._lock:
            if server.state != "connected":
                raise ToolError(
                    f"mcp server {server_name} is {server.state}: {server.error}"
                )

        async def enqueue() -> object:
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            assert server.queue is not None
            await server.queue.put((tool, arguments, future))
            return await future

        handle = asyncio.run_coroutine_threadsafe(enqueue(), self._loop)
        try:
            outcome = handle.result(timeout=timeout)
        except TimeoutError:
            handle.cancel()
            raise ToolError(f"mcp tool call timed out: {server_name}.{tool}") from None
        if isinstance(outcome, ToolError):
            raise outcome
        return str(outcome)

    def agent_tools(self) -> list[AgentTool]:
        tools: list[AgentTool] = []
        with self._lock:
            snapshot = [
                (name, list(server.tools))
                for name, server in self._servers.items()
                if server.state == "connected" and server.config.confirmed
            ]
        for server_name, infos in snapshot:
            for info in infos:
                def handler(
                    arguments: dict, _server=server_name, _tool=info.name
                ) -> str:
                    return self.call_tool(_server, _tool, arguments)

                tools.append(
                    AgentTool(
                        name=f"{server_name}.{info.name}",
                        description=info.description,
                        parameters=info.parameters,
                        handler=handler,
                    )
                )
        return tools


_active: MCPManager | None = None


def set_active(manager: MCPManager | None) -> None:
    global _active
    _active = manager


def active_tools() -> list[AgentTool]:
    if _active is None:
        return []
    return _active.agent_tools()


def active_manager() -> MCPManager | None:
    return _active


# Built-in server candidates for the settings agent tab. All start disabled
# and unconfirmed; the standard enable + confirm gates apply after adding.
# Paths the servers need (memory file, filesystem workspace) are filled in
# from the data root by candidate_entries, never typed by the user.
BUILTIN_CANDIDATES = (
    {
        "name": "fetch",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "install_hint": "pip install uv（提供 uvx）",
        "heavy": False,
    },
    {
        "name": "memory",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env_memory_file": True,
        "install_hint": "安裝 Node.js（提供 npx）",
        "heavy": False,
    },
    {
        "name": "filesystem",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        "workspace_arg": True,
        "install_hint": "安裝 Node.js（提供 npx）",
        "heavy": False,
    },
    {
        "name": "playwright",
        "command": "npx",
        "args": ["@playwright/mcp@latest", "--headless", "--isolated"],
        "install_hint": "安裝 Node.js（提供 npx）",
        "heavy": True,
    },
)


def candidate_entries(data_root, which=None):
    import shutil as _shutil
    from pathlib import Path as _Path

    which = which or _shutil.which
    root = _Path(data_root)
    entries = []
    for spec in BUILTIN_CANDIDATES:
        args = list(spec["args"])
        env: dict[str, str] = {}
        if spec.get("workspace_arg"):
            args.append(str(root))
        if spec.get("env_memory_file"):
            env["MEMORY_FILE_PATH"] = str(root / "mcp-memory.json")
        entries.append(
            {
                "name": spec["name"],
                "available": which(spec["command"]) is not None,
                "install_hint": spec["install_hint"],
                "heavy": spec["heavy"],
                "config": {
                    "transport": "stdio",
                    "command": spec["command"],
                    "args": args,
                    "env": env,
                    "url": "",
                    "auth_token": "",
                    "enabled": False,
                    "confirmed": False,
                },
            }
        )
    return entries
