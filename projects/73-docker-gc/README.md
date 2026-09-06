# Homelab Multi-Node Container Image Pruner & Cache Garbage Collector

Automated maintenance daemon to prevent Docker image layer bloat and buildx cache accumulation on NVMe pool (`/volume2`) and Raspberry Pi 5 storage.

## Safety & Retention Safeguards
- **Protected Tags:** Never prune active container images, tagged production images, or images created within the last 7 days.
- **Target Pruning:** Safely purges dangling images (`<none>:<none>`), unused build stages, and old buildx build cache.
- **Zero Host Mutation:** Controlled via Docker engine API (`/var/run/docker.sock:ro` for inspection, restricted prune endpoint).

## Architecture & Garbage Collection Policy

```mermaid
graph TD
    A[Start GC Process] --> B{Analyze Docker Images}
    B --> C{Active Container Dependency?}
    C -- Yes --> D[Keep Image]
    C -- No --> E{Created < 7 days ago?}
    E -- Yes --> D
    E -- No --> F{Tagged (Production)?}
    F -- Yes --> D
    F -- No --> G[Mark Reclaimable]
    G --> H{Threshold Met? e.g. 10GB}
    H -- Yes --> I[Prune Dangling Images & Buildx Cache]
    H -- No --> J[Skip Pruning]
```

## Running the GC

You can run this project locally using Python directly or via Docker Compose.

### Docker Compose
A `docker-compose.yml` file is provided which sets up a lightweight Python Alpine container with a read-only Docker socket and memory limit constraints (128M).
```bash
docker-compose up
```

### CLI
For manual debugging and analysis without performing destructive actions, run with the `--dry-run` flag.
```bash
python docker_gc.py --dry-run
```

Available flags:
- `--dry-run`: Dry-run mode, do not actually prune anything.
- `--threshold-gb <n>`: Threshold in GB before pruning runs (default: 10.0).
- `--keep-days <n>`: Keep images created within the last N days (default: 7).
- `--json`: Output results in JSON format.

## Scheduled Cleanup Cron Config
This script is intended to be run periodically via a schedule (e.g. daily).
```cron
# Run daily at 2:00 AM
0 2 * * * cd /path/to/projects/73-docker-gc && docker-compose up
```
