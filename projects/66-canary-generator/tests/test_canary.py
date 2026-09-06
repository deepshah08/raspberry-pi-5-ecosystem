import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock
from canary import DNSProber, HTTPProber, run_probes, SLO_VIOLATION_METRIC, DNS_LATENCY_METRIC, HTTP_TTFB_METRIC, SLO_THRESHOLD_MS

@patch('canary.dns.resolver.Resolver')
@patch('canary.time.perf_counter')
def test_dns_prober_success(mock_perf_counter, mock_resolver):
    # Setup mock perf_counter to return 0.0 then 0.045 (45ms)
    mock_perf_counter.side_effect = [0.0, 0.045]
    
    mock_resolver_instance = MagicMock()
    mock_resolver.return_value = mock_resolver_instance
    
    prober = DNSProber(["192.168.1.80"])
    results = prober.probe("pi.hole")
    
    assert "192.168.1.80" in results
    assert results["192.168.1.80"]["status"] == "success"
    assert pytest.approx(results["192.168.1.80"]["latency_ms"]) == 45.0
    mock_resolver_instance.resolve.assert_called_with("pi.hole", 'A')

@patch('canary.dns.resolver.Resolver')
@patch('canary.time.perf_counter')
def test_dns_prober_failure(mock_perf_counter, mock_resolver):
    mock_perf_counter.return_value = 0.0
    
    mock_resolver_instance = MagicMock()
    mock_resolver_instance.resolve.side_effect = Exception("Resolution failed")
    mock_resolver.return_value = mock_resolver_instance
    
    prober = DNSProber(["192.168.1.80"])
    results = prober.probe("pi.hole")
    
    assert "192.168.1.80" in results
    assert results["192.168.1.80"]["status"] == "Resolution failed"
    assert results["192.168.1.80"]["latency_ms"] == float('inf')

@patch('canary.requests.get')
@patch('canary.time.perf_counter')
def test_http_prober_success(mock_perf_counter, mock_requests_get):
    # Setup mock perf_counter to return 0.0 then 0.150 (150ms)
    mock_perf_counter.side_effect = [0.0, 0.150]
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_requests_get.return_value = mock_response
    
    prober = HTTPProber()
    results = prober.probe("http://192.168.1.100:32400")
    
    assert results["status"] == "success"
    assert results["status_code"] == 200
    assert pytest.approx(results["ttfb_ms"]) == 150.0
    mock_response.raw.read.assert_called_once()
    mock_response.close.assert_called_once()
    mock_requests_get.assert_called_with("http://192.168.1.100:32400", timeout=2.0, stream=True)

@patch('canary.requests.get')
def test_http_prober_failure(mock_requests_get):
    import requests
    mock_requests_get.side_effect = requests.exceptions.Timeout("Connection timed out")
    
    prober = HTTPProber()
    results = prober.probe("http://192.168.1.100:32400")
    
    assert results["status"] == "Connection timed out"
    assert results["status_code"] == 0
    assert results["ttfb_ms"] == float('inf')

def test_slo_evaluation():
    # Test below threshold
    is_violation = 45.0 > SLO_THRESHOLD_MS
    assert not is_violation
    
    # Test above threshold
    is_violation = 600.0 > SLO_THRESHOLD_MS
    assert is_violation
    
@patch('canary.DNSProber')
@patch('canary.HTTPProber')
def test_run_probes_dry_run(MockHTTPProber, MockDNSProber):
    mock_dns = MockDNSProber.return_value
    mock_dns.probe.return_value = {"192.168.1.80": {"latency_ms": 45.0, "status": "success"}}
    
    mock_http = MockHTTPProber.return_value
    mock_http.probe.return_value = {"ttfb_ms": 150.0, "status_code": 200, "status": "success"}
    
    results = run_probes(["192.168.1.80"], ["pi.hole"], ["http://192.168.1.100"], dry_run=True)
    
    assert "dns" in results
    assert "http" in results
    assert "slo_violations" in results
    assert results["dns"]["pi.hole"]["192.168.1.80"]["latency_ms"] == 45.0
    assert results["http"]["http://192.168.1.100"]["ttfb_ms"] == 150.0
    assert len(results["slo_violations"]) == 0

@patch('sys.argv', ['canary.py', '--probe-now', '--interval', '30', '--json', '--dry-run'])
@patch('canary.run_probes')
def test_cli_args(mock_run_probes):
    import canary
    canary.main()
    mock_run_probes.assert_called_once()
    args, kwargs = mock_run_probes.call_args
    assert kwargs['dry_run'] is True
    assert kwargs['output_json'] is True
