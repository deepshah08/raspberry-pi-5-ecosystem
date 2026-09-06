import sys
from pathlib import Path
import pytest
import responses
import os
import argparse
from unittest.mock import patch

# Ensure standalone test execution works by appending parent dir
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ddns_sentinel import WANIPDetector, CloudflareClient, DuckDNSClient, ResolutionVerifier, sync_loop
from prometheus_client import REGISTRY

@pytest.fixture
def mock_ip_responses():
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://api.ipify.org", body="192.168.1.100")
        yield rsps

@pytest.fixture
def mock_ip_responses_fail_first():
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://api.ipify.org", status=500)
        rsps.add(responses.GET, "https://ifconfig.me/ip", body="192.168.1.101")
        yield rsps

@pytest.fixture
def mock_cf_responses():
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://api.cloudflare.com/client/v4/zones/test_zone/dns_records?name=test.com&type=A",
            json={"success": True, "result": [{"id": "rec123", "content": "1.2.3.4"}]}
        )
        rsps.add(
            responses.PATCH,
            "https://api.cloudflare.com/client/v4/zones/test_zone/dns_records/rec123",
            json={"success": True}
        )
        yield rsps

@pytest.fixture
def mock_duckdns_responses():
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://www.duckdns.org/update?domains=myduck&token=duck_token&ip=1.2.3.4",
            body="OK"
        )
        yield rsps

def test_wan_ip_detector_success(mock_ip_responses):
    detector = WANIPDetector()
    ip = detector.get_public_ip(ip_version=4)
    assert ip == "192.168.1.100"

def test_wan_ip_detector_fallback(mock_ip_responses_fail_first):
    detector = WANIPDetector()
    ip = detector.get_public_ip(ip_version=4)
    assert ip == "192.168.1.101"

def test_cloudflare_client(mock_cf_responses):
    client = CloudflareClient("fake_token", "test_zone")
    record = client.get_record("test.com")
    assert record is not None
    assert record["id"] == "rec123"
    assert record["content"] == "1.2.3.4"

    success = client.update_record("rec123", "test.com", "1.2.3.5")
    assert success is True

def test_duckdns_client(mock_duckdns_responses):
    client = DuckDNSClient("duck_token")
    success = client.update_record("myduck.duckdns.org", "1.2.3.4")
    assert success is True

@patch("dns.resolver.Resolver.resolve")
def test_resolution_verifier(mock_resolve):
    class MockAnswer:
        def __init__(self, address):
            self.address = address

    mock_resolve.return_value = [MockAnswer("1.2.3.4")]

    verifier = ResolutionVerifier()
    assert verifier.verify("test.com", "1.2.3.4") is True
    assert verifier.verify("test.com", "1.2.3.5") is False

@patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "token", "DUCKDNS_TOKEN": "duck_token"})
@patch("ddns_sentinel.WANIPDetector.get_public_ip")
@patch("ddns_sentinel.CloudflareClient.get_record")
@patch("ddns_sentinel.CloudflareClient.update_record")
@patch("ddns_sentinel.DuckDNSClient.update_record")
@patch("ddns_sentinel.ResolutionVerifier.verify")
@patch("time.sleep")
def test_sync_loop(mock_sleep, mock_verify, mock_duck_update, mock_cf_update, mock_cf_get, mock_get_ip):
    # Setup mocks
    # Iteration 1: IPv4 = 192.168.1.100, IPv6 = None
    # Iteration 2: IPv4 = 192.168.1.101, IPv6 = None
    # Wait, side_effect needs enough items
    mock_get_ip.side_effect = [
        "192.168.1.100", None,
        "192.168.1.101", None,
        "192.168.1.101", None
    ]
    mock_cf_get.return_value = {"id": "rec1", "content": "old_ip"}
    mock_cf_update.return_value = True
    mock_duck_update.return_value = True
    mock_verify.return_value = True

    # Reset prometheus metric state
    from prometheus_client import REGISTRY
    import ddns_sentinel
    ddns_sentinel.homelab_ddns_ip_changed_total._value.set(0)
    ddns_sentinel.homelab_ddns_sync_success._value.set(0)
    ddns_sentinel.homelab_ddns_propagation_verified.set(0)

    # Force the loop to exit after 2 iterations (4 calls because ipv4 and ipv6 per iteration)
    def side_effect(*args):
        if mock_get_ip.call_count >= 4:
            raise KeyboardInterrupt()
    mock_sleep.side_effect = side_effect

    args = argparse.Namespace(
        check_now=False,
        dry_run=False,
        domain="myduck.duckdns.org",
        zone_id="zone123",
        json=False
    )

    try:
        sync_loop(args)
    except KeyboardInterrupt:
        pass

    ip_changed = REGISTRY.get_sample_value('homelab_ddns_ip_changed_total')
    assert ip_changed is not None and ip_changed >= 1

    sync_success = REGISTRY.get_sample_value('homelab_ddns_sync_success_total')
    assert sync_success is not None and sync_success >= 1

    prop_verified = REGISTRY.get_sample_value('homelab_ddns_propagation_verified')
    assert prop_verified == 1.0

def test_cli_args():
    import sys
    test_args = ["ddns_sentinel.py", "--check-now", "--zone-id", "abc", "--domain", "test.com", "--dry-run", "--json"]
    with patch.object(sys, 'argv', test_args):
        from ddns_sentinel import get_args
        args = get_args()
        assert args.check_now is True
        assert args.zone_id == "abc"
        assert args.domain == "test.com"
        assert args.dry_run is True
        assert args.json is True
