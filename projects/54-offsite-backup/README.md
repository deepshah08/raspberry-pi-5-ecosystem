# Project 54: Automated Off-Site Encrypted Rclone Backup & Snapshot Orchestrator

## Architecture Guide

This project automates the backup of critical data to S3-compatible cloud storage using `rclone crypt` for pure client-side zero-knowledge encryption.
It uses SQLite `VACUUM INTO` for online, safe backups without locking databases.

```mermaid
graph TD
    A[Source Directories (e.g. SQLite, AppData)] -->|VACUUM INTO / Copy| B(Staging Directory on NVMe)
    B -->|Rclone Sync with Crypt| C{Cloud Storage (B2/Wasabi)}
    B --> D[Retention Manager]
    C --> D
    D -->|Prune Old Snapshots| B & C
```

## Rclone Crypt Configuration Steps

1. Run `rclone config`
2. Create a new remote (`n`).
3. Name it (e.g., `crypt-remote`).
4. Select `Crypt` type.
5. Provide the underlying remote path (e.g., `b2-remote:backup-bucket/encrypted`).
6. Enter a strong password for encryption and salt.

## Disaster Recovery Restore Procedure

1. Install `rclone` and configure `rclone.conf` with the `crypt` remote password.
2. Run `rclone copy crypt-remote: /path/to/restore/dir` to decrypt and download the data.
3. Stop the corresponding services.
4. Replace the old SQLite databases and appdata with the downloaded data.
5. Restart services.

## Retention Policy

The `RetentionManager` will keep snapshots for a configurable number of days (default: 7).
It purges local snapshots exceeding this policy to free up NVMe staging storage.
