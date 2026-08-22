"""24/7 Discord voice-channel joiner with a Render health server."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Optional

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("voice-joiner")

TOKEN = os.getenv("DISCORD_TOKEN")
VOICE_CHANNEL_ID_RAW = os.getenv("VOICE_CHANNEL_ID")
PORT = int(os.getenv("PORT", "10000"))
RECONNECT_SECONDS = max(10, int(os.getenv("RECONNECT_SECONDS", "30")))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is required")
if not VOICE_CHANNEL_ID_RAW:
    raise RuntimeError("VOICE_CHANNEL_ID is required")
try:
    VOICE_CHANNEL_ID = int(VOICE_CHANNEL_ID_RAW)
except ValueError as exc:
    raise RuntimeError("VOICE_CHANNEL_ID must be a numeric Discord channel ID") from exc

app = Flask(__name__)
bot: Optional["VoiceJoinerBot"] = None


@app.get("/")
@app.get("/healthz")
def health() -> tuple:
    connected = bool(bot and bot.voice_client and bot.voice_client.is_connected())
    return jsonify(
        {
            "status": "ok",
            "service": "discord-voice-joiner",
            "voice_connected": connected,
        }
    ), 200


def run_health_server() -> None:
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


class VoiceJoinerBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.voice_client: Optional[discord.VoiceClient] = None
        self._connection_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        self.maintain_voice.start()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")
        await self.ensure_voice_connection()

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if not self.user or member.id != self.user.id:
            return

        try:
            expected = await self.get_target_channel()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not inspect the target channel after a voice-state change")
            asyncio.create_task(self.ensure_voice_connection())
            return

        if after.channel is None or after.channel.id != expected.id:
            logger.warning(
                "Voice state changed unexpectedly (before=%s, after=%s); rejoining",
                getattr(before.channel, "id", None),
                getattr(after.channel, "id", None),
            )
            asyncio.create_task(self.ensure_voice_connection())

    @tasks.loop(seconds=RECONNECT_SECONDS)
    async def maintain_voice(self) -> None:
        await self.ensure_voice_connection()

    @maintain_voice.before_loop
    async def before_maintain_voice(self) -> None:
        await self.wait_until_ready()

    async def get_target_channel(self) -> discord.VoiceChannel:
        channel = self.get_channel(VOICE_CHANNEL_ID)
        if channel is None:
            channel = await self.fetch_channel(VOICE_CHANNEL_ID)
        if not isinstance(channel, discord.VoiceChannel):
            raise TypeError(f"Channel {VOICE_CHANNEL_ID} is not a voice channel")
        return channel

    async def ensure_voice_connection(self) -> None:
        async with self._connection_lock:
            try:
                target = await self.get_target_channel()
                current = self.voice_client

                if current and current.is_connected() and current.channel:
                    if current.channel.id == target.id:
                        return
                    logger.warning("Bot is in channel %s; moving to %s", current.channel.id, target.id)
                    await current.move_to(target)
                    return

                if current:
                    await current.disconnect(force=True)

                logger.info("Connecting to voice channel %s", target.id)
                self.voice_client = await target.connect(reconnect=True, timeout=30)
                logger.info("Connected to %s", target.name)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Voice connection attempt failed; will retry")


def main() -> None:
    global bot
    bot = VoiceJoinerBot()
    health_thread = threading.Thread(target=run_health_server, name="health-server", daemon=True)
    health_thread.start()
    try:
        bot.run(TOKEN, reconnect=True)
    finally:
        if not bot.is_closed():
            asyncio.run(bot.close())


if __name__ == "__main__":
    main()