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
from waitress import serve

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("voice-joiner")

app = Flask(__name__)
bot: Optional["VoiceJoinerBot"] = None


@app.route("/", methods=["GET"])
@app.route("/healthz", methods=["GET"])
def health() -> tuple[dict[str, str], int]:
    """Return immediately; health checks must not depend on Discord."""
    return jsonify({"status": "ok"}), 200


def run_health_server() -> None:
    """Serve Render's health checks independently of discord.py's event loop."""
    port = int(os.environ.get("PORT", 10000))
    startup_message = f"Flask server started on port {port}"
    print(startup_message, flush=True)
    logger.info("%s (host 0.0.0.0, waitress threads=8)", startup_message)
    try:
        serve(app, host="0.0.0.0", port=port, threads=8)
    except Exception:
        logger.exception("Health server stopped unexpectedly")
        raise


class VoiceJoinerBot(commands.Bot):
    def __init__(self, voice_channel_id: int, reconnect_seconds: int) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.voice_channel_id = voice_channel_id
        self.reconnect_seconds = reconnect_seconds
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

    @tasks.loop(seconds=30)
    async def maintain_voice(self) -> None:
        await self.ensure_voice_connection()

    @maintain_voice.before_loop
    async def before_maintain_voice(self) -> None:
        await self.wait_until_ready()

    async def get_target_channel(self) -> discord.VoiceChannel:
        channel = self.get_channel(self.voice_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.voice_channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise TypeError(f"Channel {self.voice_channel_id} is not a voice channel")
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
    # Start the HTTP listener before any Discord configuration or login work.
    health_thread = threading.Thread(
        target=run_health_server,
        name="health-server",
        daemon=True,
    )
    health_thread.start()

    try:
        token = os.getenv("DISCORD_TOKEN")
        channel_id_raw = os.getenv("VOICE_CHANNEL_ID")
        if not token:
            raise RuntimeError("DISCORD_TOKEN is required")
        if not channel_id_raw:
            raise RuntimeError("VOICE_CHANNEL_ID is required")
        channel_id = int(channel_id_raw)
        reconnect_seconds = max(10, int(os.getenv("RECONNECT_SECONDS", "30")))
        bot = VoiceJoinerBot(channel_id, reconnect_seconds)
        bot.maintain_voice.change_interval(seconds=reconnect_seconds)
        bot.run(token, reconnect=True)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception:
        logger.exception("Discord bot stopped; keeping the health server available")
        health_thread.join()


if __name__ == "__main__":
    main()