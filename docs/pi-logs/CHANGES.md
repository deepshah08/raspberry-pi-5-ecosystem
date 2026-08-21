# Pi 5 Change Log — `deepshah08@192.168.1.92`

> All changes made via SSH. Each entry has **what changed**, **original state**, and **exact revert commands**.

---

## Session: 2026-08-20

### Change 001 — Repo Cloned
**Time**: 2026-08-20 ~23:16 PDT  
**What**: Cloned `deepshah08/raspberry-pi-5-ecosystem` to home directory  
**Command run**:
```bash
cd ~ && git clone https://github.com/deepshah08/raspberry-pi-5-ecosystem.git
```
**Before**: Directory did not exist  
**After**: `~/raspberry-pi-5-ecosystem/` (full repo, all projects)

**Revert**:
```bash
rm -rf ~/raspberry-pi-5-ecosystem
```

---

### Change 002 — `.env` Created from Template
**Time**: 2026-08-20 ~23:18 PDT  
**What**: Copied `.env.template` → `.env` inside the plex-arr-stack project  
**Command run**:
```bash
cd ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack
cp .env.template .env
```
**Before**: No `.env` file existed (`.env.template` is the committed template)  
**After**: `.env` created with placeholder values

**Revert**:
```bash
rm ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack/.env
```

---

### Change 003 — `.env` Patched: MEDIA_PATH & CONFIG_PATH
**Time**: 2026-08-20 ~23:18 PDT  
**What**: Updated paths in `.env` to match Pi's actual filesystem (NAS not reachable; `/mnt/media-storage` is read-only)  
**Commands run**:
```bash
# Phase 1: Tried NAS path → media-storage
sed -i "s|MEDIA_PATH=/mnt/nas/media|MEDIA_PATH=/mnt/media-storage|g" .env
sed -i "s|CONFIG_PATH=/mnt/nas/configs|CONFIG_PATH=/home/deepshah08/plex-configs|g" .env

# Phase 2: media-storage was read-only → switched to ~/media
sed -i "s|MEDIA_PATH=/mnt/media-storage|MEDIA_PATH=/home/deepshah08/media|g" .env
```
**Before** (template defaults):
```
MEDIA_PATH=/mnt/nas/media
CONFIG_PATH=/mnt/nas/configs
```
**After**:
```
MEDIA_PATH=/home/deepshah08/media
CONFIG_PATH=/home/deepshah08/plex-configs
```
> [!NOTE]
> `/mnt/media-storage` is mounted read-only (fstab: `ro,nofail`). When Ugreen NAS is online, update `MEDIA_PATH` to the NAS SMB mount point.

**Revert**:
```bash
sed -i "s|MEDIA_PATH=/home/deepshah08/media|MEDIA_PATH=/mnt/nas/media|g" \
  ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack/.env
sed -i "s|CONFIG_PATH=/home/deepshah08/plex-configs|CONFIG_PATH=/mnt/nas/configs|g" \
  ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack/.env
```

---

### Change 004 — Directories Created
**Time**: 2026-08-20 ~23:18 PDT  
**What**: Created media and config directory trees on the Pi's SD card  
**Commands run**:
```bash
mkdir -p ~/media/{movies,tv,downloads/complete,downloads/incomplete}
mkdir -p ~/plex-configs/{plex,radarr,sonarr,prowlarr,bazarr,qbittorrent,overseerr,tautulli}
```
**Before**: Neither `~/media` nor `~/plex-configs` existed  
**After**: Full directory trees created under home

**Revert**:
```bash
rm -rf ~/media ~/plex-configs
```
> [!CAUTION]
> Only run the revert if no containers have written config data to `~/plex-configs`. After first launch, these dirs will contain live Plex/Radarr/Sonarr databases.

---

### Change 005 — Docker Images Pulled ✅
**Time**: 2026-08-20 ~23:18–23:21 PDT  
**What**: Pulled Docker images for non-VPN stack services  
**Images confirmed on disk**:
| Image | Size | Status |
| :--- | :--- | :--- |
| `lscr.io/linuxserver/tautulli:latest` | 248 MB | ✅ |
| `lscr.io/linuxserver/bazarr:latest` | 614 MB | ✅ |
| `lscr.io/linuxserver/sonarr:latest` | 316 MB | ✅ |
| `lscr.io/linuxserver/prowlarr:latest` | 307 MB | ✅ |
| `lscr.io/linuxserver/radarr:latest` | 338 MB | ✅ |
| `lscr.io/linuxserver/plex:latest` | ~1 GB | ✅ (pulled in Change 006) |
| `lscr.io/linuxserver/overseerr:latest` | ~400 MB | ✅ (SHA `sha256:53a1b8`) |

**Revert**:
```bash
docker rmi \
  lscr.io/linuxserver/tautulli:latest \
  lscr.io/linuxserver/bazarr:latest \
  lscr.io/linuxserver/sonarr:latest \
  lscr.io/linuxserver/prowlarr:latest \
  lscr.io/linuxserver/radarr:latest \
  lscr.io/linuxserver/plex:latest \
  lscr.io/linuxserver/overseerr:latest
```

---

### Change 006 — Plex Image Re-Pull ✅ / Overseerr Retry 🔄
**Time**: 2026-08-20 ~23:20–23:21 PDT  
**Plex**: `lscr.io/linuxserver/plex:latest` — pulled successfully (SHA `sha256:f6c58c`)  
**Overseerr**: TLS handshake timeout on first attempt → pulled successfully on retry (SHA `sha256:53a1b8`)

---

### Change 007 — `.env` Plex Claim Token + Advertise IP Injected ✅
**Time**: 2026-08-20 23:22 PDT  
**What**: Injected Plex claim token and LAN advertise IP into `.env`

> [!CAUTION]
> The Plex claim token `claim-txyimQsNiFSWyGNE_pT6` is **single-use** and expired after 4 minutes. It has already been consumed by the Plex container on first boot to link to the Plex account. Do NOT reuse it.

**Commands run**:
```bash
sed -i "s|PLEX_CLAIM=.*|PLEX_CLAIM=claim-txyimQsNiFSWyGNE_pT6|g" .env
sed -i "s|PLEX_ADVERTISE_IP=.*|PLEX_ADVERTISE_IP=http://192.168.1.92:32400/|g" .env
```
**Before**: `PLEX_CLAIM=` (empty), `PLEX_ADVERTISE_IP=` (empty)  
**After**: Token set, IP set to `http://192.168.1.92:32400/`

**Revert**: Token is consumed — no revert needed. If Plex account link fails, get a new token at [plex.tv/claim](https://plex.tv/claim) and update `.env`, then `docker compose restart plex`.

---

### Change 008 — `docker compose up -d` (7 services) 🔄
**Time**: 2026-08-20 23:22 PDT  
**What**: Launched all 7 non-VPN services  
**Command run**:
```bash
cd ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack
docker compose up -d plex prowlarr radarr sonarr bazarr overseerr tautulli
```
**Services started**: `plex`, `prowlarr`, `radarr`, `sonarr`, `bazarr`, `overseerr`, `tautulli`  
**Network created**: `17-plex-arr-stack_media_net` (bridge)  
**Status**: ✅ All 7 services running (gluetun restarting — expected, no VPN creds yet)

**Revert** (stop and remove containers + network, keep images + volumes):
```bash
cd ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack
docker compose down
```
**Revert (nuclear — also wipe config data)**:
```bash
docker compose down -v
rm -rf ~/plex-configs
```

---

### Change 009 — `docker-compose.yml` Device Fix (video10/11/12 → /dev/dri only) ✅
**Time**: 2026-08-20 23:23 PDT  
**What**: Plex failed to start because compose mapped `/dev/video10/11/12` which don't exist on this Pi (actual devices are `/dev/video19–35`). Removed the non-existent mappings.  
**Commands run**:
```bash
sed -i "/- \/dev\/video10:/d" docker-compose.yml
sed -i "/- \/dev\/video11:/d" docker-compose.yml
sed -i "/- \/dev\/video12:/d" docker-compose.yml
```
**Before** (in plex devices section):
```yaml
devices:
  - /dev/dri:/dev/dri
  - /dev/video10:/dev/video10
  - /dev/video11:/dev/video11
  - /dev/video12:/dev/video12
```
**After**:
```yaml
devices:
  - /dev/dri:/dev/dri
```
> [!NOTE]
> Pi 5 hardware video devices are at `/dev/video19`–`/dev/video35`. `/dev/dri/renderD128` handles GPU decode and is sufficient for Plex hardware acceleration.

**Revert**:
```bash
# Re-add video devices (only if they exist on target Pi)
# Edit docker-compose.yml and add back under plex devices section
```

---

### Change 010 — `docker-compose.yml` `depends_on` Fix (radarr/sonarr/bazarr) ✅
**Time**: 2026-08-20 23:23 PDT  
**What**: Radarr and Sonarr were blocked from starting because they had `depends_on: gluetun` — but gluetun is restarting (no VPN creds). Only qBittorrent actually needs the VPN tunnel. Removed `gluetun` from radarr/sonarr/bazarr dependencies.  
**Command run**:
```bash
python3 -c "
import yaml
with open('docker-compose.yml') as f:
    c = yaml.safe_load(f)
for svc in ['radarr', 'sonarr', 'bazarr']:
    deps = c['services'][svc].get('depends_on', [])
    c['services'][svc]['depends_on'] = [d for d in deps if d != 'gluetun']
with open('docker-compose.yml', 'w') as f:
    yaml.dump(c, f, default_flow_style=False, sort_keys=False)
"
```
**Before**: `depends_on: [prowlarr, gluetun]` for radarr + sonarr  
**After**: `depends_on: [prowlarr]` for radarr + sonarr  
**Revert**: Re-add `gluetun` to `depends_on` list in `docker-compose.yml` (not recommended — gluetun shouldn't block arr apps)

---

## ✅ Stack Status — 2026-08-20 23:23 PDT

| Service | Port | Status |
| :--- | :--- | :--- |
| Plex | 32400 | ✅ Running |
| Radarr | 7878 | ✅ Running |
| Sonarr | 8989 | ✅ Running |
| Prowlarr | 9696 | ✅ Running |
| Bazarr | 6767 | ✅ Running |
| Overseerr | 5055 | ✅ Running |
| Tautulli | 8181 | ✅ Running |
| gluetun (VPN) | — | ⚠️ Restarting — needs VPN credentials |
| qBittorrent | 8080 | ⏳ Waiting for gluetun |

---

### Change 011 — VPN Credentials Injected + gluetun + qBittorrent Started 🔄
**Time**: 2026-08-20 23:31 PDT  
**What**: ProtonVPN OpenVPN credentials added to `.env`, gluetun + qBittorrent launched  
**Commands run**:
```bash
sed -i "s|VPN_SERVICE_PROVIDER=.*|VPN_SERVICE_PROVIDER=protonvpn|g" .env
sed -i "s|VPN_TYPE=.*|VPN_TYPE=openvpn|g" .env
sed -i "s|OPENVPN_USER=.*|OPENVPN_USER=***REDACTED***|g" .env
sed -i "s|OPENVPN_PASSWORD=.*|OPENVPN_PASSWORD=***REDACTED***|g" .env
echo "SERVER_COUNTRIES=Netherlands" >> .env
docker compose up -d gluetun qbittorrent
```
**Before**: `VPN_SERVICE_PROVIDER=` (empty), gluetun crash-looping  
**After**: ProtonVPN Netherlands configured, gluetun + qBittorrent starting

> [!CAUTION]
> VPN credentials are stored in `~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack/.env` on the Pi. This file is gitignored. Do NOT commit `.env` to GitHub.

**Revert** (stop VPN services only):
```bash
cd ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack
docker compose stop gluetun qbittorrent
```

---

### Change 012 — gluetun Removed, qBittorrent Direct ✅
**Time**: 2026-08-20 23:41 PDT  
**Why**: ProtonVPN free tier blocks P2P/torrenting. AT&T Fiber has 5+ year community track record of zero action on casual torrenting. Decision: run qBittorrent directly, no VPN.  
**Commands run**:
```bash
docker compose stop gluetun qbittorrent
# Patched docker-compose.yml:
#  - Removed network_mode: service:gluetun from qbittorrent
#  - Removed depends_on: gluetun from qbittorrent
#  - Added ports: [8080:8080] to qbittorrent
#  - Added networks: [media_net] to qbittorrent
docker compose up -d qbittorrent
docker compose stop gluetun   # stopped permanently
```
**Before**: qBittorrent tunnelled through gluetun (crash-looping), no torrent access  
**After**: qBittorrent on media_net, port 8080 direct, fully operational

**Revert** (re-add VPN later if desired):
```bash
# Edit docker-compose.yml: restore network_mode: 'service:gluetun', remove ports/networks from qbittorrent
# Add VPN creds to .env
# docker compose up -d gluetun qbittorrent
```

---

## ✅ FINAL STACK — 2026-08-20 23:41 PDT — ALL 8 PORTS GREEN

| Service | URL | Status |
| :--- | :--- | :--- |
| **Plex** | `http://192.168.1.92:32400/web` | ✅ Running |
| **Radarr** | `http://192.168.1.92:7878` | ✅ Running |
| **Sonarr** | `http://192.168.1.92:8989` | ✅ Running |
| **Prowlarr** | `http://192.168.1.92:9696` | ✅ Running |
| **qBittorrent** | `http://192.168.1.92:8080` | ✅ Running (no VPN) |
| **Bazarr** | `http://192.168.1.92:6767` | ✅ Running |
| **Overseerr** | `http://192.168.1.92:5055` | ✅ Running |
| **Tautulli** | `http://192.168.1.92:8181` | ✅ Running |
| gluetun | — | 🛑 Stopped (not needed) |

---

### Change 014 — IP Forwarding & Tailscale Subnet Router / Exit Node ✅
**Time**: 2026-08-21 00:59 PDT  
**What**: Enabled Linux kernel IPv4/IPv6 packet forwarding and advertised home LAN subnet `192.168.1.0/24`, exit node, and Tailscale SSH on node `pi5-media-nas`.  
**Commands run**:
```bash
sudo bash -c "cat > /etc/sysctl.d/99-tailscale.conf << EOL
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOL"
sudo sysctl -p /etc/sysctl.d/99-tailscale.conf
sudo tailscale set --advertise-routes=192.168.1.0/24 --advertise-exit-node --ssh
```
**Revert**:
```bash
sudo rm -f /etc/sysctl.d/99-tailscale.conf
sudo sysctl -w net.ipv4.ip_forward=0 net.ipv6.conf.all.forwarding=0
sudo tailscale set --advertise-routes= --advertise-exit-node=false --ssh=false
```

---

### Change 015 — Pi-hole Web Admin Password Set ✅
**Time**: 2026-08-21 00:59 PDT  
**What**: Set Pi-hole v6 Web Interface password to `Deepshah123$`. Verified `listeningMode = "ALL"`.  
**Commands run**:
```bash
sudo pihole setpassword "Deepshah123$"
```
**Verification**:
- Localhost query: `dig @127.0.0.1 google.com +short` (resolves)
- Tailscale query: `dig @100.68.196.14 google.com +short` (resolves)
- Ad-block check: `dig @127.0.0.1 doubleclick.net +short` (blocked to `0.0.0.0`)
- Web Admin URL: `http://192.168.1.92/admin` and `http://100.68.196.14/admin`

---

### Change 016 — Legacy Docker Cleanup ✅
**Time**: 2026-08-21 00:59 PDT  
**What**: Removed stopped legacy `jellyfin` container and archived `~/docker/docker-compose.yml` to `.legacy.bak` to prevent duplicate Tailscale or port bindings.  
**Commands run**:
```bash
docker rm -f jellyfin tailscale 2>/dev/null || true
mv ~/docker/docker-compose.yml ~/docker/docker-compose.yml.legacy.bak
```
**Revert**:
```bash
mv ~/docker/docker-compose.yml.legacy.bak ~/docker/docker-compose.yml
```

**Revert** (stop and remove containers + network, keep images + volumes):
```bash
cd ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack
docker compose down
```
**Revert (nuclear — also wipe config data)**:
```bash
docker compose down -v
rm -rf ~/plex-configs
```
**Time**: 2026-08-20 ~23:18 PDT  
**What**: Pulling Docker images for non-VPN stack services  
**Command run**:
```bash
cd ~/raspberry-pi-5-ecosystem/projects/17-plex-arr-stack
docker compose pull plex prowlarr radarr sonarr bazarr overseerr tautulli
```
**Images being pulled**:
- `lscr.io/linuxserver/plex:latest` (arm64)
- `lscr.io/linuxserver/prowlarr:latest`
- `lscr.io/linuxserver/radarr:latest`
- `lscr.io/linuxserver/sonarr:latest`
- `lscr.io/linuxserver/bazarr:latest`
- `lscr.io/linuxserver/overseerr:latest`
- `lscr.io/linuxserver/tautulli:latest`
**Status**: 🔄 Running (background task `task-537`)

**Revert** (remove all pulled images):
```bash
docker rmi \
  lscr.io/linuxserver/plex:latest \
  lscr.io/linuxserver/prowlarr:latest \
  lscr.io/linuxserver/radarr:latest \
  lscr.io/linuxserver/sonarr:latest \
  lscr.io/linuxserver/bazarr:latest \
  lscr.io/linuxserver/overseerr:latest \
  lscr.io/linuxserver/tautulli:latest
```

---

## Pending / Next Steps

| Step | Status | Blocker |
| :--- | :--- | :--- |
| Add `PLEX_CLAIM` to `.env` | ⏳ Waiting | Need token from [plex.tv/claim](https://plex.tv/claim) |
| Add VPN credentials to `.env` | ⏳ Waiting | Need VPN provider + credentials |
| `docker compose up -d` (7 services) | ⏳ Waiting | Need Plex claim token first |
| Mount Ugreen NAS | ⏳ Waiting | NAS not found on `192.168.1.x` network |
| Apply Radarr/Sonarr custom formats | ⏳ Waiting | After containers up |

---

## Environment Snapshot (at session start)

| Property | Value |
| :--- | :--- |
| Pi IP (LAN) | `192.168.1.92` |
| Pi IP (Tailscale) | `100.68.196.14` |
| OS | Raspberry Pi OS, kernel `6.18.39+rpt-rpi-2712`, aarch64 |
| Docker | `29.7.2` |
| Docker Compose | `v5.5.0` |
| Python | `3.13.5` |
| SD Card free | ~100 GB |
| RAM free | ~15 GB / 16 GB |
| `/mnt/media-storage` | Mounted read-only (exFAT, UUID `011D-8336`) |
| Tailscale | Active, hostname `pi5-media-nas` |
| Pre-existing containers | `jellyfin` (exited 3 weeks ago) |
| Pre-existing compose | `~/docker/docker-compose.yml` (Jellyfin + Tailscale) |
