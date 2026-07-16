import asyncio
from pathlib import Path
from types import SimpleNamespace

from traduko.bot.api import CoreApi
from traduko.bot.runner import TradukoBot
from traduko.config import DiscordBotConfig
from traduko.service.app import create_app


def test_command_tree_has_all_five_commands() -> None:
    client = TradukoBot(DiscordBotConfig(allowed_user_ids=["1"]), api=object())
    names = {command.name for command in client.tree.get_commands()}
    assert names == {"status", "pause", "resume", "cancel", "budget"}


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.deferred = False

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append((content, ephemeral))

    async def defer(self) -> None:
        self.deferred = True


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, content: str) -> None:
        self.messages.append(content)


def make_interaction(user_id: int):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=FakeResponse(),
        followup=FakeFollowup(),
    )


def test_unauthorized_user_gets_ephemeral_refusal() -> None:
    client = TradukoBot(DiscordBotConfig(allowed_user_ids=["42"]), api=object())
    command = client.tree.get_command("status")
    interaction = make_interaction(7)
    asyncio.run(command.callback(interaction))
    assert interaction.response.messages
    content, ephemeral = interaction.response.messages[0]
    assert ephemeral is True and "未授權" in content


def test_authorized_status_defers_then_replies(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    api = CoreApi.for_app(app)
    client = TradukoBot(DiscordBotConfig(allowed_user_ids=["42"]), api=api)
    command = client.tree.get_command("status")
    interaction = make_interaction(42)

    async def scenario() -> None:
        await command.callback(interaction)
        await api.aclose()

    asyncio.run(scenario())
    assert interaction.response.deferred is True
    assert interaction.followup.messages == ["目前沒有任何任務。"]
