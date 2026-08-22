# Discord Voice Channel Joiner

A Python Discord bot that stays connected to a configured voice channel and exposes a Render-friendly health endpoint.

## Run & Operate

- `python main.py` — run the Discord voice joiner and health server
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DISCORD_TOKEN` (secret) and `VOICE_CHANNEL_ID` (numeric channel ID)

## Stack

- Python 3.12
- Discord client: discord.py with voice support
- Health server: Flask
- Deployment: Render Web Service

## Where things live

- `main.py` — Discord client, reconnection loop, and Flask health endpoint
- `requirements.txt` — pinned Python dependencies
- `render.yaml` / `Procfile` — Render service configuration
- `.env.example` — local configuration template
- `README.md` — setup and deployment instructions

## Architecture decisions

- A guarded periodic loop is the source of truth for connection health; voice-state events trigger an immediate check for faster recovery.
- The health server runs in a daemon thread so it remains responsive while discord.py owns its asyncio event loop.
- Secrets are read only from environment variables and are never written to the repository.

## Product

The service joins the configured Discord voice channel at startup and persistently attempts to return after disconnects, kicks, moves, or transient Discord/network errors.

## User preferences

- Deploy target is Render and source of truth is the requested GitHub repository.

## Gotchas

- The bot needs Connect and Speak permissions in the target channel.
- `DISCORD_TOKEN` must be configured as a secret; never commit `.env`.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
