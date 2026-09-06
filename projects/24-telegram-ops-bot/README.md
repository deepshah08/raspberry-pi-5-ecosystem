# AI Telegram Media & Operations Bot v2

This project provides a unified homelab operations Telegram bot integrating with various services across the infrastructure.

## Setup

1. **BotFather Configuration:**
   - Talk to `@BotFather` on Telegram.
   - Use `/newbot` to create a new bot and get the `TELEGRAM_TOKEN`.
   - Configure commands using `/setcommands` with the following list:
     ```
     start - Start the bot
     search - Search media using OmniSearch
     briefing - Generate morning briefing
     status - Check homelab status
     ingest - Check camera ingest status
     ```

2. **Environment Variables:**
   Create a `.env` file or export the following variables:
   - `TELEGRAM_TOKEN`: Your bot token.
   - `TELEGRAM_ADMIN_IDS`: Comma-separated list of authorized chat IDs.
   - (Optional) Service URLs: `OMNISEARCH_URL`, `AUDIOBOOKSHELF_URL`, `UPTIME_KUMA_URL`, `CAMERA_INGEST_URL`.

3. **Live Testing:**
   To run the bot locally via Docker Compose:
   ```bash
   cd projects/24-telegram-ops-bot
   docker-compose up -d
   ```
   Check logs using:
   ```bash
   docker-compose logs -f
   ```

## Commands

- `/search <query>`: Queries OmniSearch Gateway (Port 8008) and returns top matches.
- `/briefing`: Triggers on-demand morning briefing generation via Audiobookshelf (Port 13378).
- `/status`: Queries Uptime Kuma (Port 3001) and returns a clean markdown status report.
- `/ingest`: Checks SD card camera ingest status.
