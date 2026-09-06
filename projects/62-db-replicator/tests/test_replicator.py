import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Ensure replicator can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from replicator import WALReplicator


@pytest.fixture
def setup_db():
    temp_dir = tempfile.TemporaryDirectory()
    dir_path = Path(temp_dir.name)

    source_db = dir_path / "test.db"
    replica_dir = dir_path / "replica"
    replica_dir.mkdir(parents=True, exist_ok=True)

    # Initialize DB with WAL mode
    conn = sqlite3.connect(source_db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, value TEXT);")
    cursor.execute("INSERT INTO test_table (value) VALUES ('initial');")
    conn.commit()

    # Don't close connection, otherwise WAL might get auto-checkpointed and deleted
    # if it's the last connection, leaving no .db-wal file.

    yield source_db, replica_dir

    conn.close()
    temp_dir.cleanup()


def test_wal_detection(setup_db):
    source_db, replica_dir = setup_db
    replicator = WALReplicator(str(source_db), str(replica_dir))

    # Initially should be True since last_wal_state is None
    assert replicator.detect_wal_changes() is True

    # Next call should be False
    assert replicator.detect_wal_changes() is False

    # Modify DB to change WAL
    time.sleep(0.01) # ensure mtime change
    conn = sqlite3.connect(source_db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO test_table (value) VALUES ('new_data');")
    conn.commit()
    conn.close()

    # Should detect changes again
    assert replicator.detect_wal_changes() is True


def test_passive_checkpoint(setup_db):
    source_db, replica_dir = setup_db
    replicator = WALReplicator(str(source_db), str(replica_dir))

    # Connect and leave connection open to simulate production read
    prod_conn = sqlite3.connect(source_db)
    cursor = prod_conn.cursor()
    cursor.execute("SELECT * FROM test_table;")

    # Checkpoint should still succeed passively
    assert replicator.run_passive_checkpoint() is True

    prod_conn.close()


def test_sync_and_verify(setup_db):
    source_db, replica_dir = setup_db
    replicator = WALReplicator(str(source_db), str(replica_dir))

    assert replicator.sync_replica() is True
    assert replicator.verify_replica() is True

    # Verify replica has data
    replica_db = replica_dir / source_db.name
    conn = sqlite3.connect(replica_db)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM test_table;")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1


def test_dry_run(setup_db):
    source_db, replica_dir = setup_db
    replicator = WALReplicator(str(source_db), str(replica_dir), dry_run=True)

    # Should return True but do nothing
    assert replicator.run_passive_checkpoint() is True
    assert replicator.sync_replica() is True
    assert replicator.verify_replica() is True

    # Replica DB should not exist
    replica_db = replica_dir / source_db.name
    assert not replica_db.exists()


def test_error_handling(setup_db):
    source_db, replica_dir = setup_db

    # Non-existent source
    replicator = WALReplicator(str(source_db.with_name("nonexistent.db")), str(replica_dir))
    assert replicator.detect_wal_changes() is False
    assert replicator.run_passive_checkpoint() is False
    assert replicator.sync_replica() is False
    assert replicator.verify_replica() is False
