import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess
import pytest
import json

# Ensure standalone test execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cold_sync import check_standby, run_sync, spindown_drive, get_device_from_path, main

def test_get_device_from_path():
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/sdb1 100 50 50 50% /mnt/usb\n"
        mock_run.return_value = mock_result

        device = get_device_from_path('/mnt/usb')
        assert device == '/dev/sdb'

def test_check_standby_active():
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "Device is ACTIVE"
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        assert not check_standby('/dev/sdb')

def test_check_standby_standby():
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "Device is in STANDBY mode"
        mock_result.returncode = 2
        mock_run.return_value = mock_result

        assert check_standby('/dev/sdb')

def test_run_sync_success():
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = "Sync output"
        mock_run.return_value = mock_result

        success, out = run_sync('/src', '/dst', '60M', False)
        assert success
        assert out == "Sync output"

        # Verify rsync is called with correct arguments
        mock_run.assert_called_with(['rsync', '-av', '--bwlimit=60M', '/src', '/dst'], check=True, capture_output=True, text=True)

def test_spindown_drive():
    with patch('subprocess.run') as mock_run:
        assert spindown_drive('/dev/sdb')

        # Should be called twice (sync, then hdparm)
        assert mock_run.call_count == 2
        mock_run.assert_any_call(['sync'], check=True)
        mock_run.assert_any_call(['hdparm', '-y', '/dev/sdb'], check=True, capture_output=True, text=True)

class SystemExitInterrupt(Exception):
    pass

def test_main_no_sync_now():
    with patch('sys.argv', ['cold_sync.py', '--source', '/src', '--target', '/dst', '--json']), \
         patch('sys.exit', side_effect=SystemExitInterrupt) as mock_exit, \
         patch('builtins.print') as mock_print:

        try:
            main()
        except SystemExitInterrupt:
            pass

        # sys.exit(0) should be called
        mock_exit.assert_called_once_with(0)

        # Print should be called with json
        mock_print.assert_called()
        output = json.loads(mock_print.call_args[0][0])
        assert output['status'] == 'started'
        assert not output['sync_success']

def test_main_sync_aborted_by_standby():
    with patch('sys.argv', ['cold_sync.py', '--sync-now', '--source', '/src', '--target', '/dst', '--json']), \
         patch('cold_sync.get_device_from_path', return_value='/dev/sdb'), \
         patch('cold_sync.check_standby', return_value=True), \
         patch('sys.exit', side_effect=SystemExitInterrupt) as mock_exit, \
         patch('builtins.print') as mock_print:

        try:
            main()
        except SystemExitInterrupt:
            pass

        mock_exit.assert_called_once_with(0)
        output = json.loads(mock_print.call_args[0][0])
        assert output['status'] == 'aborted'
        assert output['standby_aborted']

def test_main_sync_success():
    with patch('sys.argv', ['cold_sync.py', '--sync-now', '--source', '/src', '--target', '/dst', '--json']), \
         patch('cold_sync.get_device_from_path', return_value='/dev/sdb'), \
         patch('cold_sync.check_standby', return_value=False), \
         patch('cold_sync.run_sync', return_value=(True, "Success")), \
         patch('cold_sync.spindown_drive', return_value=True), \
         patch('builtins.print') as mock_print:
        main()

        output = json.loads(mock_print.call_args[0][0])
        assert output['status'] == 'success'
        assert output['sync_success']
        assert output['spindown_success']
