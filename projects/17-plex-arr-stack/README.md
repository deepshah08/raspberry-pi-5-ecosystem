# Plex + *arr Media Automation Stack

## 1. Overview & Stack Diagram

This stack provides a fully automated media server environment running on Raspberry Pi 5. It automatically fetches movies and TV shows (with a focus on Hindi and English audio, along with English subtitles), organizes them using hardlinks for efficient storage, and serves them via Plex.

| Service | Port | Purpose |
| --------- | ------ | --------- |
| **Plex** | 32400 | Media streaming and cataloging server |
| **Radarr** | 7878 | Movie automation, search, and management |
| **Sonarr** | 8989 | TV show automation, search, and management |
| **Bazarr** | 6767 | Automatic subtitle fetcher (English/Hindi) |
| **Prowlarr** | 9696 | Indexer manager/proxy for Radarr and Sonarr |
| **Overseerr** | 5055 | Media request and discovery frontend |
| **qBittorrent** | 8080 | Torrent download client (routed via VPN) |
| **Gluetun** | 8000 | VPN client to keep download traffic secure and private |
| **Tautulli** | 8181 | Plex monitoring, analytics, and notifications |

## 2. Prerequisites

- **Hardware:** Raspberry Pi 5 (4GB+ RAM recommended)
- **Software:** Docker & Docker Compose v2 installed
- **Storage:** Ugreen NAS DXP 2800 mounted at `/mnt/nas`
- **Privacy:** VPN subscription. Supported providers include:
  - NordVPN
  - Mullvad
  - ProtonVPN
  - Surfshark
  - ExpressVPN
- **Account:** A free [Plex account](https://www.plex.tv/)

## 3. Quick Start

```bash
# 1. Clone / navigate
cd projects/17-plex-arr-stack

# 2. Copy and fill env
cp .env.template .env
nano .env  # Fill in PLEX_CLAIM, VPN credentials, etc.

# 3. Validate env
python scripts/validate_env.py

# 4. One-command setup
bash scripts/first_run_setup.sh

# 5. Apply language filters
export RADARR_API_KEY=<your-key>  # Found in Radarr > Settings > General
python config/radarr_apply_config.py
export SONARR_API_KEY=<your-key>
python config/sonarr_apply_config.py
export BAZARR_API_KEY=<your-key>
python config/bazarr_apply_config.py
```

## 4. .env Configuration Reference

| Environment Variable | Description | Example Value | Required/Optional |
| ---------------------- | ------------- | --------------- | ------------------- |
| `PUID` | User ID for file permissions | `1000` | Required |
| `PGID` | Group ID for file permissions | `1000` | Required |
| `TZ` | Timezone | `America/Los_Angeles` | Required |
| `PLEX_CLAIM` | Plex claim token for server auth | `claim-xxxxxxxxx` | Required |
| `VPN_SERVICE_PROVIDER` | Name of your VPN provider | `nordvpn` | Required |
| `OPENVPN_USER` | VPN username | `your-vpn-user` | Required |
| `OPENVPN_PASSWORD` | VPN password | `your-vpn-pass` | Required |
| `SERVER_REGIONS` | VPN region to connect to | `us` | Optional |
| `MEDIA_PATH` | Base media storage path on NAS | `/mnt/nas/media` | Required |
| `CONFIG_PATH` | Persistent configuration storage path on NAS | `/mnt/nas/configs` | Required |

## 5. Service Web UIs

| Service | URL | Purpose | Default Login |
| --------- | ----- | --------- | --------------- |
| **Plex** | `http://<IP>:32400/web` | Media Streaming | Plex Account |
| **Radarr** | `http://<IP>:7878` | Movie Management | None / Configure on setup |
| **Sonarr** | `http://<IP>:8989` | TV Show Management | None / Configure on setup |
| **Bazarr** | `http://<IP>:6767` | Subtitles | None / Configure on setup |
| **Prowlarr** | `http://<IP>:9696` | Indexer Management | None / Configure on setup |
| **Overseerr** | `http://<IP>:5055` | Media Requests | Plex Auth |
| **qBittorrent** | `http://<IP>:8080` | Download Client | `admin` / `adminadmin` |
| **Tautulli** | `http://<IP>:8181` | Analytics & Alerts | None / Configure on setup |

## 6. First-Boot Checklist

1. **Prowlarr:** Add indexers (Torrentio, 1337x, YTS, RARBG mirrors). Link to Radarr/Sonarr.
2. **Radarr:** Settings > Quality > Create '1080p Hindi' profile. Set custom format scores.
3. **Sonarr:** Same as Radarr.
4. **Bazarr:** Verify English subtitle providers are active. Test with a movie.
5. **Overseerr:** Connect to Plex, Radarr, Sonarr. Set up user request limits.
6. **Tautulli:** Connect to Plex. Optionally configure Discord notifications.

## 7. Language Filter Setup (Manual UI Steps)

After running `radarr_apply_config.py`, go to **Radarr > Settings > Quality Profiles**.

- Edit your profile, scroll to Custom Formats
- Set scores: Hindi Audio: 500, Dual Audio: 400, Hindi Dubbed: 300, English Audio: 200, Non EN-HI Audio: -1000
- *(Look for the Custom Formats section at the bottom of the Quality Profile edit modal)*

## 8. NAS Directory Structure

```text
/mnt/nas/
├── configs/           # Persistent application configs (Plex, Radarr, Sonarr, etc.)
└── media/
    ├── movies/        # Final destination for movies (hardlinked)
    ├── tv/            # Final destination for TV shows (hardlinked)
    └── downloads/     # Temporary & seeding location for qBittorrent
        ├── movies/
        └── tv/
```

- `/mnt/nas/media/downloads/` is where qBittorrent saves incomplete and completed torrents.
- `/mnt/nas/media/movies/` and `/mnt/nas/media/tv/` are where Radarr and Sonarr organize the final media for Plex.

## 9. Hardlinks Explained

This stack uses a single volume mount (e.g., `/data` mapped to `/mnt/nas/media`) to enable instant atomic moves (no re-copy after download). Since the original download and the final renamed file are on the same filesystem, Radarr and Sonarr create hardlinks. This means zero extra disk space is used and files are available in Plex immediately while qBittorrent continues to seed.

## 10. South Indian / Gujarati Movies

Note that these should be manually downloaded and dropped into `/mnt/nas/media/movies/` — Plex auto-scans every 15 minutes and will pick them up.

## 11. Troubleshooting

- **qBittorrent not connecting** → check gluetun VPN is running
- **Radarr can't find Hindi releases** → verify custom format scores are assigned in quality profile
- **Bazarr not downloading subtitles** → check OpenSubtitles API key / daily limit
- **Plex not transcoding** → verify `/dev/dri` device exists on Pi 5

## 12. Validation Commands

```bash
python scripts/validate_env.py
python scripts/validate_stack.py
docker compose ps
docker compose logs -f radarr
```
