# Continuous SQLite WAL & State Replication Sentry

The Continuous SQLite WAL & State Replication Sentry provides near-zero Recovery Point Objective (RPO) for critical SQLite databases (like Audiobookshelf, Uptime Kuma, and custom event buses) by safely streaming Write-Ahead Log (WAL) frames to a replica location without interrupting production writes.

## Architecture Guide

The service operates entirely autonomously by monitoring the `.db-wal` file. When changes are detected, it performs a non-blocking passive checkpoint on a read-only database connection, synchronizes the database files to the replica, and verifies integrity using SQLite's native `PRAGMA integrity_check`.

### WAL Replication Sequence

```mermaid
sequenceDiagram
    participant P as Production Container (Writer)
    participant DB as Source SQLite (db + wal)
    participant R as Replicator Daemon
    participant Rep as Replica Directory

    P->>DB: Normal write operations (WAL appends)
    loop Every Interval
        R->>DB: Detects `.db-wal` file modification
        alt Changes Detected
            R->>DB: Connect (mode=ro)
            R->>DB: PRAGMA wal_checkpoint(PASSIVE)
            Note right of DB: Non-blocking; lock-free checkpoint
            R->>Rep: Copy `.db`, `.db-wal`, `.db-shm`
            R->>Rep: Connect & PRAGMA integrity_check
        end
    end
```

### Non-Blocking Checkpoints

The replicator uses `PRAGMA wal_checkpoint(PASSIVE);` on a connection opened with `mode=ro`. A passive checkpoint synchronizes as many frames as possible from the WAL into the main database without interfering with readers or writers. It does not attempt to obtain exclusive locks, thus guaranteeing zero contention with production processes.

## Point-in-Time Recovery Runbook

In the event of database corruption or failure in the production environment:

1. **Stop Production Services:** Ensure that the application writing to the database is fully stopped to prevent partial writes.
2. **Backup Current State:** Move the corrupted or current database files (`.db`, `.db-wal`, `.db-shm`) to a safe quarantine location.
3. **Restore from Replica:** Copy the synchronized `.db`, `.db-wal`, and `.db-shm` files from the replica directory into the production directory.
4. **Fix Permissions:** Ensure the restored files have the correct ownership and permissions for the production application container.
5. **Restart Services:** Start the production container. SQLite will automatically process any pending WAL frames upon the first connection, restoring state.
