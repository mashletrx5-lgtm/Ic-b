# Discord Voice Channel Joiner

A small Python service that keeps a Discord bot connected to one configured voice channel. It is designed for Render web services and exposes a health endpoint so the service can be monitored.

## Discord setup

1. Create an application and bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable the bot's **Connect** and **Speak** permissions for the target voice channel.
3. Invite the bot to the server with the `bot` scope and those permissions.
4. Enable Developer Mode in Discord, right-click the target voice channel, and choose **Copy Channel ID**.

This bot does not play audio, so it does not request or need the Message Content intent.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your token and channel ID.
python main.py
```

The health endpoint is available at `http://localhost:10000/healthz`.

## Deploy on Render

Create a **Web Service** from this repository. Render will read `render.yaml`, or use:

- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`

Add these environment variables in Render:

- `DISCORD_TOKEN`: the bot token
- `VOICE_CHANNEL_ID`: the numeric target voice-channel ID

Render supplies `PORT` automatically; the service defaults to `10000` when run elsewhere. Use `/healthz` as the health-check path if configuring one manually.

The bot joins on startup, rejoins after a disconnect or kick, moves back if it is moved to another voice channel, and retries failed connection attempts every 30 seconds.