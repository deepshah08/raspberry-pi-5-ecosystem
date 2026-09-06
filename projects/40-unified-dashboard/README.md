# Project 40: Unified Search & Daily Briefing PWA Dashboard

This project provides a modern, responsive Single-Page Application (SPA/PWA) Dashboard acting as the central hub for the homelab. It serves as a unified interface to query the OmniSearch Gateway, listen to daily briefings via Audiobookshelf, and monitor homelab health via Uptime Kuma.

## Features
- **OmniSearch Bar:** Debounced natural language search querying OmniSearch (Port 8008). Displays confidence badges, timestamp jumpers, and an image preview lightbox.
- **Morning Briefing Player:** Built-in audio player streaming the latest briefing from Audiobookshelf (Port 13378).
- **Homelab Health Sentry:** Live status widget displaying operational metrics querying Uptime Kuma (Port 3001).

## Architecture & Ports

The dashboard runs as a single FastAPI backend with proxy endpoints resolving CORS issues and hiding internal ports.

- **Dashboard Service (This Project):** `http://localhost:3030`
- **OmniSearch Proxy Target:** `http://localhost:8008`
- **Audiobookshelf Proxy Target:** `http://localhost:13378`
- **Uptime Kuma Proxy Target:** `http://localhost:3001`

```
[Browser] <--> [FastAPI (3030)] <--> [OmniSearch (8008)]
                                <--> [Audiobookshelf (13378)]
                                <--> [Uptime Kuma (3001)]
```

## Running the Dashboard

```bash
cd projects/40-unified-dashboard
docker-compose up -d
```
Access the dashboard at `http://localhost:3030`.

## Testing

A comprehensive test suite uses `pytest` and `fastapi.testclient`. Mocking is implemented for external services to ensure tests run reliably without dependencies.

```bash
cd projects/40-unified-dashboard
pip install -r requirements.txt
PYTHONPATH=. pytest tests/
```

## UI Mockup

```text
===================================================
| Unified Dashboard              [🟢 All Systems] |
|-------------------------------------------------|
|                                                 |
| OmniSearch Gateway                              |
| [ Search across all media...             ]      |
|                                                 |
| ----------------------------------------------- |
| Result Title                        [95% Match] |
| Result snippet...                               |
| [IMAGE PREVIEW]            [Jump to 01:23]      |
| ----------------------------------------------- |
|                                                 |
| Morning Briefing                                |
| [Play] Latest Briefing ------------- [00:00]    |
|                                                 |
===================================================
```
