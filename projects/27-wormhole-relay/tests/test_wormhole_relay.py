import sys
import time
from pathlib import Path

# Add project root to path for standalone execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wormhole_relay import TransitSentry, StorageCleaner, main
from prometheus_client import REGISTRY

def test_transit_sentry_tracking():
    sentry = TransitSentry()
    token = "test-token-123"

    # Check start
    sentry.start_transfer(token)
    assert token in sentry.sessions
    assert sentry.sessions[token].is_active is True
    assert sentry.sessions[token].bytes_transferred == 0

    # Check update
    sentry.update_transfer(token, 1024)
    assert sentry.sessions[token].bytes_transferred == 1024

    # Check end
    sentry.end_transfer(token)
    assert sentry.sessions[token].is_active is False

def test_prometheus_metrics():
    # Start fresh metrics via REGISTRY
    sentry = TransitSentry()
    token = "metric-token-456"

    # Before
    active_before = REGISTRY.get_sample_value('homelab_wormhole_active_transfers') or 0

    # Start
    sentry.start_transfer(token)
    active_after = REGISTRY.get_sample_value('homelab_wormhole_active_transfers') or 0
    assert active_after == active_before + 1

    # Update
    bytes_before = REGISTRY.get_sample_value('homelab_wormhole_bytes_transferred_total') or 0
    sentry.update_transfer(token, 2048)
    bytes_after = REGISTRY.get_sample_value('homelab_wormhole_bytes_transferred_total') or 0
    assert bytes_after == bytes_before + 2048

    # End
    sentry.end_transfer(token)
    active_final = REGISTRY.get_sample_value('homelab_wormhole_active_transfers') or 0
    assert active_final == active_before

def test_buffer_cleanup(tmp_path):
    cleaner = StorageCleaner(buffer_dir=str(tmp_path), retention_seconds=1)

    # Create test file
    test_file = tmp_path / "staging_data.tmp"
    test_file.write_text("dummy data")

    # Shouldn't prune yet
    pruned = cleaner.clean(dry_run=False)
    assert len(pruned) == 0
    assert test_file.exists()

    # Wait for retention limit
    time.sleep(1.1)

    # Dry run
    pruned_dry = cleaner.clean(dry_run=True)
    assert len(pruned_dry) == 1
    assert test_file.exists() # Should still exist

    # Actual run
    pruned = cleaner.clean(dry_run=False)
    assert len(pruned) == 1
    assert not test_file.exists() # Should be deleted

def test_cli_flags(capsys, tmp_path):
    # Test --audit-now with --json
    test_file = tmp_path / "audit_test.tmp"
    test_file.write_text("data")

    # Mock time so it gets pruned
    old_stat = test_file.stat()
    import os
    os.utime(test_file, (old_stat.st_atime, old_stat.st_mtime - 3601))

    args = [
        '--audit-now',
        '--buffer-dir', str(tmp_path),
        '--dry-run',
        '--json'
    ]
    main(args)

    captured = capsys.readouterr()
    import json
    output = json.loads(captured.out)

    assert output['dry_run'] is True
    assert len(output['pruned_files']) == 1
    assert str(test_file) in output['pruned_files'][0]
    assert test_file.exists() # Because of dry-run
