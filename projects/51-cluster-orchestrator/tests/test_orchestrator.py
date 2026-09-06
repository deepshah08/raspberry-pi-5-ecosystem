import pytest
import argparse
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Allow running from repository root or project folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import orchestrator

@pytest.fixture
def dummy_config():
    return {
        'tiers': {
            1: {
                'name': 'Tier 1',
                'services': {
                    'svc1': {'host': '1.1.1.1', 'compose_dir': '/dir1', 'healthcheck': 'http://url1', 'grace_period': 5}
                }
            },
            2: {
                'name': 'Tier 2',
                'services': {
                    'svc2': {'host': '2.2.2.2', 'compose_dir': '/dir2', 'healthcheck': 'http://url2', 'grace_period': 10}
                }
            }
        }
    }

def test_dry_run_up(dummy_config):
    args = argparse.Namespace(command='up', tier=None, dry_run=True, timeout=5)

    with patch('orchestrator.run_command') as mock_run_command:
        with patch('orchestrator.wait_for_tier_health') as mock_wait:
            orchestrator.up(args, dummy_config)

            # Since it's a dry run, run_command should be called with dry_run=True
            assert mock_run_command.call_count == 2 # svc1 and svc2

            # Healthcheck should not be called in dry run
            mock_wait.assert_not_called()

def test_up_ordering_and_healthcheck(dummy_config):
    args = argparse.Namespace(command='up', tier=None, dry_run=False, timeout=5)

    with patch('orchestrator.run_command') as mock_run_command, \
         patch('orchestrator.wait_for_tier_health') as mock_wait:

        mock_wait.return_value = True # Simulate healthy

        orchestrator.up(args, dummy_config)

        # Check ordering, tier 1 then tier 2
        calls = mock_run_command.call_args_list
        assert 'svc1' not in str(calls[1]) and 'dir1' in str(calls[0]) # naive check
        assert 'dir2' in str(calls[1])
        assert mock_wait.call_count == 2

def test_up_timeout_halts(dummy_config):
    args = argparse.Namespace(command='up', tier=None, dry_run=False, timeout=5)

    with patch('orchestrator.run_command'), \
         patch('orchestrator.wait_for_tier_health') as mock_wait, \
         pytest.raises(SystemExit):

        # Simulate tier 1 failing
        mock_wait.return_value = False

        orchestrator.up(args, dummy_config)

def test_down_reverse_ordering(dummy_config):
    args = argparse.Namespace(command='down', tier=None, dry_run=False, timeout=5)

    with patch('orchestrator.run_command') as mock_run_command:
        orchestrator.down(args, dummy_config)

        # 2 services * 2 commands (sync, stop) = 4 commands
        assert mock_run_command.call_count == 4

        calls = mock_run_command.call_args_list
        # Reverse ordering: tier 2 first, then tier 1
        assert '2.2.2.2' in str(calls[0]) # Sync tier 2
        assert 'dir2' in str(calls[1])    # Stop tier 2
        assert '1.1.1.1' in str(calls[2]) # Sync tier 1
        assert 'dir1' in str(calls[3])    # Stop tier 1

def test_health_parallel(dummy_config):
    args = argparse.Namespace(command='health', json=False, dry_run=False, timeout=5)

    with patch('orchestrator.check_health') as mock_check:
        mock_check.side_effect = [True, False] # svc1 healthy, svc2 unhealthy

        with patch('builtins.print') as mock_print:
            orchestrator.health(args, dummy_config)

            # Both services should be checked
            assert mock_check.call_count == 2

            # Check print outputs
            output = "\n".join([args[0][0] for args in mock_print.call_args_list])
            assert "svc1: HEALTHY" in output
            assert "svc2: UNHEALTHY" in output

def test_check_health_success():
    with patch('requests.get') as mock_get:
        mock_get.return_value.status_code = 200
        assert orchestrator.check_health('http://test', 5) == True

def test_check_health_failure():
    with patch('requests.get') as mock_get:
        mock_get.return_value.status_code = 500
        assert orchestrator.check_health('http://test', 5) == False

def test_check_health_exception():
    with patch('requests.get', side_effect=Exception("Connection error")):
        assert orchestrator.check_health('http://test', 5) == False
