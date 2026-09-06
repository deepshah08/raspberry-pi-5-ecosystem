# Audiobookshelf to Plex Media Matcher & Progress Sync

This service provides bi-directional synchronization of playback progress and listen states between Audiobookshelf (podcasts/audiobooks) and Plex (music/podcast libraries).

## Architecture & Sequence

```mermaid
sequenceDiagram
    participant ABS as Audiobookshelf
    participant Sync as Sync Daemon
    participant Plex as Plex Media Server

    Sync->>ABS: Fetch listening sessions & timestamps
    ABS-->>Sync: Return progress data
    Sync->>Plex: Query /status/sessions & metadata
    Plex-->>Sync: Return progress data
    Sync->>Sync: Harmonize progress (match titles, resolve conflicts)
    alt Update ABS
        Sync->>ABS: Sync Progress
    else Update Plex
        Sync->>Plex: Sync Progress
    end
```

## Setup

1. Configure `ABS_URL`, `ABS_TOKEN`, `PLEX_URL`, and `PLEX_TOKEN` in the environment or `docker-compose.yml`.
2. Run `docker-compose up -d`.

## Conflict Resolution Rules

- Progress is matched between systems using fuzzy title matching.
- The system with the most recently updated timestamp (`updatedAt`) wins.
- Optionally, a direction can be forced using the `--force-direction` CLI flag (`abs-to-plex` or `plex-to-abs`).
