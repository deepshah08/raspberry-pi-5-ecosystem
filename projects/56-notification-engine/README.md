# Project 56: Multi-Channel Alert Router & Rate-Limiting Notification Engine

## Overview

The Notification Engine is an alert dispatcher designed to bridge the Homelab Event Bus (Project 53), SMART Sentinel (Project 49), Synthetic Canaries (Project 45), and Backup Orchestrators (Projects 43 & 54). It features robust anti-flooding, de-duplication, and dynamic severity-based routing.

## Features

- **Anti-Flooding & De-duplication**: Uses hash fingerprints (source + title) to suppress duplicate alerts within a configurable cooldown window.
- **Dynamic Severity Routing**:
  - **CRITICAL**: Dispatches to Telegram with high-priority markdown and audio chime, and to NTFY.
  - **WARNING**: Dispatches to Telegram standard channel.
  - **INFO**: Logs (and queues to WebSocket bus for Unified Dashboard & Morning Briefing digest).
- **Zero Host Mutation**: Fully containerized and isolated Python service.

## Architecture & Routing

```mermaid
flowchart TD
    A[Event Sources: SMART Sentinel, Canaries, Backup Orchestrators] -->|Alert (Source, Title, Body, Severity)| B[Notification Engine / router.py]
    B --> C{Deduplication Check}
    C -- Duplicate in Cooldown Window --> D[Suppress Alert]
    C -- New Alert / Cooldown Expired --> E{Severity Router}
    E -- CRITICAL --> F[Telegram Bot API (High Priority)]
    E -- CRITICAL --> G[NTFY Webhook]
    E -- WARNING --> H[Telegram Bot API (Standard)]
    E -- INFO --> I[Log / Event Bus Queue]
```

## Configuration

Set the following environment variables in your environment or via `.env` for Docker:

- `TELEGRAM_BOT_TOKEN`: Your Telegram Bot API token.
- `TELEGRAM_CHAT_ID`: The target Telegram Chat ID.
- `NTFY_TOPIC_URL`: The URL to your NTFY topic (e.g., `https://ntfy.sh/my-homelab-alerts`).

## Usage (CLI)

You can run the router as a standalone script for testing:

```bash
python router.py --send-test --severity CRITICAL --title "Disk Space Critical" --body "NAS /volume1 is 98% full." --source "SMART Sentinel"
```

## Cooldown Tuning

The default cooldown window for de-duplication is 30 minutes (1800 seconds). You can adjust this by passing the `cooldown_seconds` parameter when instantiating the `AlertRouter` class.
