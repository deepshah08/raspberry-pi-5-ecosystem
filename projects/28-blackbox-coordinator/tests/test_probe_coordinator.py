import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, mock_open, MagicMock
from probe_coordinator import ServiceDiscoverySurveyor

def test_service_discovery_surveyor(mocker):
    surveyor = ServiceDiscoverySurveyor(nodes=["192.168.1.92"], ports=[80, 5432])
    
    mock_socket = mocker.patch('socket.socket')
    mock_instance = mock_socket.return_value.__enter__.return_value
    
    def connect_ex_mock(address):
        # 192.168.1.92:80 is open, 5432 is closed
        if address == ("192.168.1.92", 80):
            return 0
        return 1
        
    mock_instance.connect_ex.side_effect = connect_ex_mock
    
    discovered = surveyor.discover()
    
    assert len(discovered) == 2 # 1 icmp + 1 http
    
    icmp_target = next((d for d in discovered if d["module"] == "icmp"), None)
    assert icmp_target is not None
    assert icmp_target["target"] == "192.168.1.92"
    
    http_target = next((d for d in discovered if d["module"] == "http_2xx"), None)
    assert http_target is not None
    assert http_target["target"] == "http://192.168.1.92:80"
    assert http_target["node"] == "192.168.1.92"
    assert http_target["port"] == 80

def test_target_config_synthesizer(mocker):
    from probe_coordinator import TargetConfigSynthesizer
    
    discovered_services = [
        {"target": "http://192.168.1.92:80", "module": "http_2xx", "node": "192.168.1.92", "port": 80},
        {"target": "192.168.1.80:5432", "module": "tcp_connect", "node": "192.168.1.80", "port": 5432}
    ]
    
    mock_file = mock_open()
    mocker.patch("builtins.open", mock_file)
    
    config = TargetConfigSynthesizer.synthesize(discovered_services, output_path="dummy.yml")
    
    assert len(config) == 2
    
    # Check correct grouping
    http_config = next((c for c in config if c["labels"]["module"] == "http_2xx"), None)
    assert http_config is not None
    assert http_config["targets"] == ["http://192.168.1.92:80"]
    
    tcp_config = next((c for c in config if c["labels"]["module"] == "tcp_connect"), None)
    assert tcp_config is not None
    assert tcp_config["targets"] == ["192.168.1.80:5432"]
    
    mock_file.assert_called_once_with("dummy.yml", 'w')

def test_probe_evaluator(mocker):
    from probe_coordinator import ProbeEvaluator
    
    discovered_services = [
        {"target": "http://192.168.1.92:80", "module": "http_2xx", "node": "192.168.1.92", "port": 80},
        {"target": "192.168.1.80:5432", "module": "tcp_connect", "node": "192.168.1.80", "port": 5432},
        {"target": "http://192.168.1.92:8080", "module": "http_2xx", "node": "192.168.1.92", "port": 8080}, # will fail
        {"target": "192.168.1.92", "module": "icmp", "node": "192.168.1.92", "port": 0}
    ]
    
    mock_requests_get = mocker.patch("requests.get")
    mock_socket = mocker.patch("socket.socket")
    mock_subprocess = mocker.patch("subprocess.run")
    mock_socket_instance = mock_socket.return_value.__enter__.return_value
    
    # http_2xx logic
    def mock_get(url, **kwargs):
        mock_resp = MagicMock()
        if url == "http://192.168.1.92:80":
            mock_resp.status_code = 200
        else:
            mock_resp.status_code = 500
        return mock_resp
        
    mock_requests_get.side_effect = mock_get
    
    # tcp_connect logic
    mock_socket_instance.connect_ex.return_value = 0 # 5432 is open
    
    # icmp logic
    mock_subprocess.return_value = MagicMock(returncode=0)
    
    stats = ProbeEvaluator.evaluate(discovered_services)
    
    assert stats["total_targets"] == 4
    assert stats["healthy_probes"] == 3
    assert stats["healthy_ratio"] == 3/4
    assert "avg_latency" in stats


def test_prometheus_exporter(mocker):
    from probe_coordinator import PrometheusExporter
    
    mocker.patch("probe_coordinator.start_http_server")
    mock_gauge = mocker.patch("probe_coordinator.Gauge")
    
    exporter = PrometheusExporter()
    exporter.start()
    
    stats = {
        "total_targets": 10,
        "healthy_probes": 5,
        "healthy_ratio": 0.5
    }
    exporter.update_metrics(stats)
    
    assert mock_gauge.return_value.set.call_count == 2

    # Test with latency
    stats_with_latency = {
        "total_targets": 10,
        "healthy_probes": 5,
        "healthy_ratio": 0.5,
        "avg_latency": 0.1
    }
    exporter.update_metrics(stats_with_latency)
    
    # +3 calls for total_targets, healthy_ratio, and avg_latency
    assert mock_gauge.return_value.set.call_count == 5
    
def test_cli_main(mocker):
    from probe_coordinator import main
    
    # Mock everything
    mocker.patch("argparse.ArgumentParser.parse_args", return_value=MagicMock(scan_now=True, output_config="test.yml", dry_run=False, json=False))
    
    mock_exporter_cls = mocker.patch("probe_coordinator.PrometheusExporter")
    mock_surveyor_cls = mocker.patch("probe_coordinator.ServiceDiscoverySurveyor")
    mock_synthesizer = mocker.patch("probe_coordinator.TargetConfigSynthesizer")
    mock_evaluator = mocker.patch("probe_coordinator.ProbeEvaluator")
    
    mock_surveyor_instance = mock_surveyor_cls.return_value
    mock_surveyor_instance.discover.return_value = [{"target": "http://192.168.1.92:80"}]
    
    mock_evaluator.evaluate.return_value = {"total_targets": 1, "healthy_probes": 1, "healthy_ratio": 1.0}
    
    main()
    
    mock_exporter_cls.return_value.start.assert_called_once()
    mock_surveyor_instance.discover.assert_called_once()
    mock_synthesizer.synthesize.assert_called_once_with([{"target": "http://192.168.1.92:80"}], output_path="test.yml")
    mock_evaluator.evaluate.assert_called_once()
    mock_exporter_cls.return_value.update_metrics.assert_called_once()
