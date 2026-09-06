import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest
import requests_mock
from proxy_sentry import UpstreamAuditor, HealthProber, METRIC_HEALTHY, METRIC_RTT, METRIC_SSL_EXPIRY
from prometheus_client import REGISTRY

@pytest.fixture
def mock_req():
    with requests_mock.Mocker() as m:
        yield m

def test_auditor_traefik_api(mock_req):
    traefik_data = {
        "http": {
            "routers": {
                "my-router": {
                    "rule": "Host(`example.com`)",
                    "service": "my-service"
                }
            },
            "services": {
                "my-service": {
                    "loadBalancer": {
                        "servers": [
                            {"url": "http://10.0.0.1:8080"}
                        ]
                    }
                }
            }
        }
    }

    mock_req.get("http://traefik.api/api/http/routers", json=traefik_data)

    # Normally auditor expects the whole json structure, so let's feed it
    mock_req.get("http://traefik.api/config", json=traefik_data)

    auditor = UpstreamAuditor(api_url="http://traefik.api/config")
    routes = auditor.get_routes()

    assert len(routes) == 1
    assert routes[0]["host"] == "example.com"
    assert routes[0]["upstream"] == "http://10.0.0.1:8080"


def test_auditor_caddy_json(tmp_path):
    caddy_data = {
        "apps": {
            "http": {
                "servers": {
                    "srv0": {
                        "routes": [
                            {
                                "match": [{"host": ["caddy.example.com"]}],
                                "handle": [
                                    {
                                        "handler": "reverse_proxy",
                                        "upstreams": [{"dial": "10.0.0.2:9000"}]
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }
    config_file = tmp_path / "caddy.json"
    with open(config_file, "w") as f:
        json.dump(caddy_data, f)

    auditor = UpstreamAuditor(config_path=str(config_file), is_json=True)
    routes = auditor.get_routes()

    assert len(routes) == 1
    assert routes[0]["host"] == "caddy.example.com"
    assert routes[0]["upstream"] == "http://10.0.0.2:9000"


def test_health_prober_success(mock_req):
    route = {"host": "test.com", "upstream": "http://test.local"}
    mock_req.get("http://test.local", text="ok", status_code=200)

    prober = HealthProber()
    result = prober.probe(route)

    assert result["host"] == "test.com"
    assert result["upstream"] == "http://test.local"
    assert result["healthy"] == 1
    assert result["status_code"] == 200
    assert result["rtt"] > 0
    assert result["ssl_days"] is None


def test_health_prober_fail(mock_req):
    route = {"host": "fail.com", "upstream": "http://fail.local"}
    mock_req.get("http://fail.local", text="error", status_code=502)

    prober = HealthProber()
    result = prober.probe(route)

    assert result["healthy"] == 0
    assert result["status_code"] == 502

def test_metrics_update(mock_req):
    host = "metric.com"
    upstream = "http://metric.local"

    # Ensure metrics start clean
    try:
        val_healthy = REGISTRY.get_sample_value('homelab_proxy_upstreams_healthy', {'host': host, 'upstream': upstream})
    except Exception:
        val_healthy = None

    METRIC_HEALTHY.labels(host=host, upstream=upstream).set(1)
    METRIC_RTT.labels(host=host, upstream=upstream).set(0.15)

    val_healthy_new = REGISTRY.get_sample_value('homelab_proxy_upstreams_healthy', {'host': host, 'upstream': upstream})
    val_rtt_new = REGISTRY.get_sample_value('homelab_proxy_upstream_rtt_seconds', {'host': host, 'upstream': upstream})

    assert val_healthy_new == 1.0
    assert val_rtt_new == 0.15
