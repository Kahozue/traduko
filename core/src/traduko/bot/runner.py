"""discord.py wiring: gateway client, slash command registration and the
progress consumer. Everything with logic lives in commands/render/progress;
this module stays a thin adapter. Replies are zh-TW user-facing copy (same
deliberate exception as render.py).
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from ..config import DiscordBotConfig
from . import commands as bot_commands
from .api import CoreApi
from .progress import consume_events

logger = logging.getLogger(__name__)


class TradukoBot(discord.Client):
    def __init__(self, config: DiscordBotConfig, api) -> None:
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.tree = build_tree(self, api, config)

    async def setup_hook(self) -> None:
        if self.config.guild_id:
            guild = discord.Object(id=int(self.config.guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        logger.info("discord bot ready as %s", self.user)


def build_tree(
    client: discord.Client, api, config: DiscordBotConfig
) -> app_commands.CommandTree:
    tree = app_commands.CommandTree(client)
    allowed = config.allowed_user_ids

    async def reply(interaction: discord.Interaction, build) -> None:
        if not bot_commands.is_authorized(interaction.user.id, allowed):
            await interaction.response.send_message(
                bot_commands.UNAUTHORIZED, ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            content = await build()
        except Exception:
            logger.exception("bot command failed")
            content = "指令執行失敗，請查看 core 日誌。"
        await interaction.followup.send(content)

    @tree.command(name="status", description="查看任務狀態")
    @app_commands.describe(task_id="任務 ID，留空則列出最近任務")
    async def status(
        interaction: discord.Interaction, task_id: str | None = None
    ) -> None:
        await reply(interaction, lambda: bot_commands.status_command(api, task_id))

    @tree.command(name="pause", description="暫停執行中的任務")
    @app_commands.describe(task_id="任務 ID")
    async def pause(interaction: discord.Interaction, task_id: str) -> None:
        await reply(interaction, lambda: bot_commands.pause_command(api, task_id))

    @tree.command(name="resume", description="續跑已暫停或待確認的任務")
    @app_commands.describe(task_id="任務 ID")
    async def resume(interaction: discord.Interaction, task_id: str) -> None:
        await reply(interaction, lambda: bot_commands.resume_command(api, task_id))

    @tree.command(name="cancel", description="取消任務")
    @app_commands.describe(task_id="任務 ID")
    async def cancel(interaction: discord.Interaction, task_id: str) -> None:
        await reply(interaction, lambda: bot_commands.cancel_command(api, task_id))

    @tree.command(name="budget", description="查看或調整預算上限")
    @app_commands.describe(
        task_limit="單任務上限（USD 數字，或 off 表示不設上限）",
        monthly_limit="每月上限（USD 數字，或 off 表示不設上限）",
    )
    async def budget(
        interaction: discord.Interaction,
        task_limit: str | None = None,
        monthly_limit: str | None = None,
    ) -> None:
        await reply(
            interaction,
            lambda: bot_commands.budget_command(api, task_limit, monthly_limit),
        )

    return tree


class ChannelMessenger:
    """Posts and edits progress messages in one configured channel."""

    def __init__(self, client: discord.Client, channel_id: int) -> None:
        self._client = client
        self._channel_id = channel_id

    async def _channel(self):
        await self._client.wait_until_ready()
        channel = self._client.get_channel(self._channel_id)
        if channel is None:
            channel = await self._client.fetch_channel(self._channel_id)
        return channel

    async def post(self, content: str):
        return await (await self._channel()).send(content)

    async def edit(self, ref, content: str) -> None:
        await ref.edit(content=content)


async def run_bot(app, config: DiscordBotConfig) -> None:
    """Run gateway client and progress consumer until cancelled.

    Owned by the service lifespan; the bot reaches the core exclusively
    through the HTTP API (ASGI transport), like any other client.
    """
    api = CoreApi.for_app(app)
    client = TradukoBot(config, api)
    consumer: asyncio.Task | None = None
    client_id: int | None = None
    broadcaster = app.state.broadcaster
    try:
        if config.channel_id:
            client_id, queue = broadcaster.register()
            messenger = ChannelMessenger(client, int(config.channel_id))
            consumer = asyncio.create_task(consume_events(queue, api, messenger))
        await client.start(config.resolve_token())
    finally:
        if consumer is not None:
            consumer.cancel()
        if client_id is not None:
            broadcaster.unregister(client_id)
        if not client.is_closed():
            await client.close()
        await api.aclose()
