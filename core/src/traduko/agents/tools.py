"""Agent tool registry: named tools with parameter schemas, plug-in style.

Tools are the only way an agent touches the world. Each tool declares its
parameters so the model sees an explicit contract and the runner can
reject malformed calls before they reach the handler.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class ToolError(Exception):
    pass


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict[str, dict]
    handler: Callable[[dict], str]

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ToolError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> AgentTool:
        if name not in self._tools:
            raise ToolError(f"unknown tool: {name}")
        return self._tools[name]

    def specs(self) -> list[dict]:
        return [self._tools[name].spec() for name in self.names()]

    def execute(self, name: str, arguments: dict) -> str:
        tool = self.get(name)
        missing = [
            param
            for param, schema in tool.parameters.items()
            if schema.get("required") and param not in arguments
        ]
        if missing:
            raise ToolError(f"{name}: missing arguments: {', '.join(missing)}")
        unknown = [key for key in arguments if key not in tool.parameters]
        if unknown:
            raise ToolError(f"{name}: unknown arguments: {', '.join(unknown)}")
        return tool.handler(arguments)
