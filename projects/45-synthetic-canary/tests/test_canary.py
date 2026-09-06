import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
from prometheus_client import REGISTRY

# We need to add the canary_runner module to sys.path to import it
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import canary_runner

@pytest.fixture(autouse=True)
def reset_metrics():
    # Reset failure counts before each test
    canary_runner.failure_counts.clear()

@pytest.mark.asyncio
async def test_dns_probe_success(mocker):
    mock_resolve = mocker.patch('dns.asyncresolver.Resolver.resolve', new_callable=AsyncMock)
    mock_resolve.return_value = MagicMock()

    target = canary_runner.DNS_TARGETS[0]

    # Run the probe
    await canary_runner.probe_dns(target, dry_run=True)

    # Assert successful resolution
    mock_resolve.assert_called_once_with('google.com', 'A')

    # Check metrics
    success_val = REGISTRY.get_sample_value('canary_probe_success', labels={'target': target['name'], 'type': 'dns'})
    assert success_val == 1.0

    duration_val = REGISTRY.get_sample_value('canary_probe_duration_seconds', labels={'target': target['name'], 'type': 'dns'})
    assert duration_val >= 0.0

@pytest.mark.asyncio
async def test_dns_probe_slo_breach(mocker):
    # Simulate slow response
    async def slow_resolve(*args, **kwargs):
        await asyncio.sleep(0.6)
        return MagicMock()

    mocker.patch('dns.asyncresolver.Resolver.resolve', side_effect=slow_resolve)
    mock_alert = mocker.patch('canary_runner.send_telegram_alert', new_callable=AsyncMock)

    target = canary_runner.DNS_TARGETS[0]

    # Initial violation count
    initial_violations = REGISTRY.get_sample_value('canary_slo_violation_count_total', labels={'target': target['name'], 'type': 'dns'}) or 0.0

    await canary_runner.probe_dns(target, dry_run=False)

    # Assert alert was sent
    mock_alert.assert_called_once()
    assert "SLO breached" in mock_alert.call_args[0][0]

    # Assert violation count increased
    new_violations = REGISTRY.get_sample_value('canary_slo_violation_count_total', labels={'target': target['name'], 'type': 'dns'}) or 0.0
    assert new_violations == initial_violations + 1.0

@pytest.mark.asyncio
async def test_dns_probe_consecutive_failure(mocker):
    # Simulate timeout/failure
    mocker.patch('dns.asyncresolver.Resolver.resolve', side_effect=Exception("Timeout"))
    mock_alert = mocker.patch('canary_runner.send_telegram_alert', new_callable=AsyncMock)

    target = canary_runner.DNS_TARGETS[0]

    # First failure - no alert
    await canary_runner.probe_dns(target, dry_run=False)
    assert canary_runner.failure_counts[target['name']] == 1
    mock_alert.assert_not_called()

    # Second failure - should trigger alert
    await canary_runner.probe_dns(target, dry_run=False)
    mock_alert.assert_called_once()
    assert "consecutively" in mock_alert.call_args[0][0]

    # Counter reset
    assert canary_runner.failure_counts[target['name']] == 0

@pytest.mark.asyncio
async def test_http_probe_success(mocker):
    mock_get = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    mocker.patch('httpx.AsyncClient.get', new=mock_get)

    target = canary_runner.HTTP_TARGETS[0]

    await canary_runner.probe_http(target, dry_run=True)

    mock_get.assert_called_once_with(target['url'], timeout=5.0)

    success_val = REGISTRY.get_sample_value('canary_probe_success', labels={'target': target['name'], 'type': 'http'})
    assert success_val == 1.0

@pytest.mark.asyncio
async def test_http_probe_slo_breach(mocker):
    async def slow_get(*args, **kwargs):
        await asyncio.sleep(1.1) # > 1000ms
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        return mock_response

    mocker.patch('httpx.AsyncClient.get', side_effect=slow_get)
    mock_alert = mocker.patch('canary_runner.send_telegram_alert', new_callable=AsyncMock)

    target = canary_runner.HTTP_TARGETS[0]

    await canary_runner.probe_http(target, dry_run=False)

    mock_alert.assert_called_once()
    assert "SLO breached" in mock_alert.call_args[0][0]

@pytest.mark.asyncio
async def test_http_probe_consecutive_failure(mocker):
    mocker.patch('httpx.AsyncClient.get', side_effect=httpx.ConnectError("Connection refused"))
    mock_alert = mocker.patch('canary_runner.send_telegram_alert', new_callable=AsyncMock)

    target = canary_runner.HTTP_TARGETS[0]

    # First failure
    await canary_runner.probe_http(target, dry_run=False)
    assert canary_runner.failure_counts[target['name']] == 1
    mock_alert.assert_not_called()

    # Second failure
    await canary_runner.probe_http(target, dry_run=False)
    mock_alert.assert_called_once()
    assert "consecutively" in mock_alert.call_args[0][0]

@pytest.mark.asyncio
async def test_send_telegram_alert(mocker):
    mocker.patch.dict('os.environ', {'TELEGRAM_BOT_TOKEN': 'test_token', 'TELEGRAM_CHAT_ID': 'test_chat'})
    # Reload credentials in module since they are loaded at top level
    canary_runner.TELEGRAM_BOT_TOKEN = 'test_token'
    canary_runner.TELEGRAM_CHAT_ID = 'test_chat'

    mock_post = AsyncMock()
    mock_post.return_value.raise_for_status = MagicMock()
    mocker.patch('httpx.AsyncClient.post', new=mock_post)

    await canary_runner.send_telegram_alert("Test alert", dry_run=False)

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "sendMessage" in args[0]
    assert kwargs['json']['text'] == "🚨 *SLO Violation / Canary Alert* 🚨\nTest alert"
