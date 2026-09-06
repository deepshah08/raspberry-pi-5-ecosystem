# Homelab Unified CLI & Multi-Node Cluster Orchestrator (`labctl`)

`labctl` is a unified developer and operator CLI for managing homelab services across a multi-node setup (UGREEN NAS and Raspberry Pi 5).

## Architecture

```mermaid
flowchart TD
    CLI[labctl CLI] --> NodeExporter[Node Exporter (9100)]
    CLI --> UptimeKuma[Uptime Kuma (3001)]
    CLI --> OmniSearch[OmniSearch Gateway (8008)]
    CLI --> SMARTSentinel[S.M.A.R.T. Sentinel (9106)]
    CLI --> Audiobookshelf[Audiobookshelf (13378)]
    CLI --> ProbeRunner[Synthetic Probes]
    CLI --> BackupOrchestrator[SMR Cold Backup Orchestrator]
```

## Setup & Alias

To use `labctl` from anywhere, add an alias to your shell profile (e.g., `~/.bashrc` or `~/.zshrc`):

```bash
alias labctl="python3 $(pwd)/labctl.py"
```

## Command Reference

### Global Options

*   `--json`: Output results in JSON format. Compatible with all subcommands. Useful for automated scripting and piping.

### `status`

Queries Uptime Kuma (port 3001) and Node Exporters (port 9100) on NAS & Pi 5 to display service statuses, CPU temperature, and RAM usage.

**Example:**
```bash
$ labctl status
Node Status:
Node | Status | CPU Temp | RAM Usage
-----+--------+----------+----------
NAS  | UP     | 45.0°C   | 15.2%
Pi 5 | UP     | 55.0°C   | 20.1%

Service Status:
Service     | Status
------------+-------
Uptime Kuma | UP
```

### `search <query>`

Queries the OmniSearch Gateway (port 8008) to display natural language matches, scores, and media paths.

**Example:**
```bash
$ labctl search "mountains"
Search Results for 'mountains':
Score  | Media Path
-------+----------------------
0.9500 | /media/mountains.jpg
0.8200 | /media/hike.jpg
```

### `smart`

Queries S.M.A.R.T. Sentinel (port 9106) for NVMe TBW wear and HDD standby states without waking sleeping disks.

**Example:**
```bash
$ labctl smart
NVMe Wear Levels (TBW Proxy):
Disk        | Wear (%)
------------+----------
/dev/nvme0n1| 5.0%

HDD Standby States:
Disk      | State
----------+--------
/dev/sdb  | STANDBY
```

### `briefing [--play]`

Queries Audiobookshelf (port 13378) for the latest synthesized morning briefing episode. Use `--play` to play it locally.

**Example:**
```bash
$ labctl briefing
Latest Morning Briefing: Briefing_2024-10-25.mp3
```

### `canary`

Runs an on-demand synthetic probe round (DNS + HTTP latency) to verify homelab SLOs (e.g., < 50ms DNS latency).

**Example:**
```bash
$ labctl canary
Synthetic Canary Probe Results:
Metric       | Value     | SLO Threshold | Status
-------------+-----------+---------------+-------
DNS Latency  | 10.5 ms   | < 50 ms       | PASSED
HTTP Latency | 150.2 ms  | N/A           | N/A
```

### `backup [--dry-run]`

Triggers the Project 43 SMR Cold Backup Orchestrator with spindown checks.

**Example:**
```bash
$ labctl backup --dry-run
Triggering backup with command: python3 projects/43-cold-backup-orchestrator/backup_orchestrator.py --source /volume1/data --target /mnt/backup --dry-run
...
```
