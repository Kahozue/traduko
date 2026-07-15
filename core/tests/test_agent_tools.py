import pytest

from traduko.agents.tools import AgentTool, ToolError, ToolRegistry


def make_echo_tool(name: str = "echo") -> AgentTool:
    return AgentTool(
        name=name,
        description="Echo the given text.",
        parameters={
            "text": {"type": "string", "required": True, "description": "text to echo"},
            "upper": {"type": "boolean", "required": False, "description": "uppercase it"},
        },
        handler=lambda args: args["text"].upper() if args.get("upper") else args["text"],
    )


def test_register_and_execute() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())
    assert registry.execute("echo", {"text": "hi"}) == "hi"
    assert registry.execute("echo", {"text": "hi", "upper": True}) == "HI"


def test_duplicate_registration_rejected() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())
    with pytest.raises(ToolError):
        registry.register(make_echo_tool())


def test_unknown_tool() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolError):
        registry.execute("nope", {})


def test_missing_required_argument() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())
    with pytest.raises(ToolError, match="missing"):
        registry.execute("echo", {})


def test_unknown_argument_rejected() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool())
    with pytest.raises(ToolError, match="unknown"):
        registry.execute("echo", {"text": "hi", "bogus": 1})


def test_specs_sorted_by_name() -> None:
    registry = ToolRegistry()
    registry.register(make_echo_tool("zeta"))
    registry.register(make_echo_tool("alpha"))
    specs = registry.specs()
    assert [s["name"] for s in specs] == ["alpha", "zeta"]
    assert specs[0]["parameters"]["text"]["required"] is True
