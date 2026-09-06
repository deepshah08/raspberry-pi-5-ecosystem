import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure standalone test execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from router import AlertRouter, Severity


@pytest.fixture
def router():
    # Provide a short cooldown for testing deduplication easily
    with patch.dict('os.environ', {
        'TELEGRAM_BOT_TOKEN': 'test_token',
        'TELEGRAM_CHAT_ID': '12345',
        'NTFY_TOPIC_URL': 'http://ntfy.sh/test_topic'
    }):
        yield AlertRouter(cooldown_seconds=1)


def test_fingerprint_generation(router):
    fp1 = router._generate_fingerprint("SourceA", "TitleA")
    fp2 = router._generate_fingerprint("SourceA", "TitleA")
    fp3 = router._generate_fingerprint("SourceB", "TitleA")

    assert fp1 == fp2
    assert fp1 != fp3


def test_deduplication(router):
    # Dispatch an alert successfully
    with patch('requests.post') as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        success, status = router.dispatch("SourceA", "Test Title", "Test Body", Severity.INFO)
        assert success is True
        assert status == "DISPATCHED"

        # Second dispatch within cooldown window should be suppressed
        success, status = router.dispatch("SourceA", "Test Title", "Test Body", Severity.INFO)
        assert success is False
        assert status == "SUPPRESSED"

        # Wait for cooldown to expire
        time.sleep(1.1)

        # Dispatch again, should succeed
        success, status = router.dispatch("SourceA", "Test Title", "Test Body", Severity.INFO)
        assert success is True
        assert status == "DISPATCHED"


@patch('requests.post')
def test_severity_critical(mock_post, router):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    success, status = router.dispatch("SourceA", "Critical Issue", "System is down", Severity.CRITICAL)

    assert success is True
    assert status == "DISPATCHED"
    assert mock_post.call_count == 2 # Once for Telegram, once for NTFY

    # Check NTFY webhook formatting
    ntfy_call = mock_post.call_args_list[1]
    args, kwargs = ntfy_call
    assert args[0] == "http://ntfy.sh/test_topic"
    assert kwargs["data"] == b"System is down"
    assert kwargs["headers"]["Title"] == "[CRITICAL] Critical Issue"
    assert kwargs["headers"]["Priority"] == "high"
    assert kwargs["headers"]["Tags"] == "rotating_light"

    # Check Telegram formatting
    telegram_call = mock_post.call_args_list[0]
    args, kwargs = telegram_call
    assert args[0] == "https://api.telegram.org/bottest_token/sendMessage"
    assert kwargs["json"]["chat_id"] == "12345"
    assert kwargs["json"]["text"] == "🚨 *CRITICAL*: Critical Issue\n\nSystem is down"
    assert kwargs["json"]["parse_mode"] == "Markdown"


@patch('requests.post')
def test_severity_warning(mock_post, router):
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response

    success, status = router.dispatch("SourceA", "Warning Issue", "Disk space low", Severity.WARNING)

    assert success is True
    assert status == "DISPATCHED"
    assert mock_post.call_count == 1 # Only Telegram


@patch('requests.post')
def test_severity_info(mock_post, router):
    success, status = router.dispatch("SourceA", "Info Issue", "Backup complete", Severity.INFO)

    assert success is True
    assert status == "DISPATCHED"
    assert mock_post.call_count == 0 # INFO doesn't trigger external webhooks


@patch('requests.post')
def test_telegram_failure_handling(mock_post, router):
    import requests
    mock_post.side_effect = requests.RequestException("Connection error")

    # Try WARNING, which only sends to Telegram
    success, status = router.dispatch("SourceA", "Warning Issue", "Disk space low", Severity.WARNING)

    assert success is False
    assert status == "FAILED"


def test_missing_config():
    with patch.dict('os.environ', clear=True):
        router = AlertRouter()

        # Since config is missing, Telegram dispatch should return False
        telegram_success = router._send_telegram("Title", "Body", Severity.WARNING)
        assert telegram_success is False

        # Same for NTFY
        ntfy_success = router._send_ntfy("Title", "Body", Severity.CRITICAL)
        assert ntfy_success is False
