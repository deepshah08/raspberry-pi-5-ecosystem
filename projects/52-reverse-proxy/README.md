# Unified Internal Reverse Proxy & Local DNS Rewrites

This project implements a lightweight Nginx reverse proxy mapped to human-friendly `.home` domains, simplifying access to various homelab services running on different ports. It includes a utility script to automatically generate Pi-hole v6 FTL local DNS records.

## Architecture

```mermaid
graph TD
    User([User Device]) -->|DNS Query| Pihole[Pi-hole DNS]
    Pihole -.->|Resolves to 192.168.1.80| User
    User -->|HTTP Requests| Nginx[Nginx Reverse Proxy]

    Nginx -->|dash.home| Dash[Unified Dashboard :3030]
    Nginx -->|search.home| Search[OmniSearch :8008]
    Nginx -->|briefing.home| Audiobookshelf[Audiobookshelf :13378]
    Nginx -->|status.home| UptimeKuma[Uptime Kuma :3001]
    Nginx -->|metrics.home| Grafana[Grafana :3000]
    Nginx -->|ai.home| LLM[LLM Gateway :8000]
```

## Domain Catalog

- `dash.home` -> Unified Dashboard (port 3030)
- `search.home` -> OmniSearch Gateway (port 8008)
- `briefing.home` -> Audiobookshelf (port 13378)
- `status.home` -> Uptime Kuma (port 3001)
- `metrics.home` -> Grafana (port 3000)
- `ai.home` -> Local LLM Gateway (port 8000)

## Security
- Internal-only binding.
- Proxy headers (`X-Forwarded-For`, `X-Real-IP`).
- WebSocket upgrade support.
- Zero public exposure.

## Pi-hole Integration

A utility script `generate_pihole_rewrites.py` parses `nginx.conf` and generates local DNS records suitable for Pi-hole's `/etc/pihole/custom.list`.

### Usage

To preview the records:
```bash
./generate_pihole_rewrites.py --target-ip 192.168.1.80 --dry-run
```

To output the records to a file:
```bash
./generate_pihole_rewrites.py --target-ip 192.168.1.80 --output custom.list
```

## Deployment

Deploy the reverse proxy using Docker Compose:

```bash
docker-compose up -d
```
