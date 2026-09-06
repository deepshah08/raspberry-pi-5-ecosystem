import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import responses

import homepage_sentry

import json
import yaml
import requests
from unittest.mock import patch

def test_parse_args():
    with patch('sys.argv', ['homepage_sentry.py', '--scan-now', '--dry-run']):
        args = homepage_sentry.parse_args()
        assert args.scan_now is True
        assert args.dry_run is True
        assert args.json is False

@responses.activate
def test_discover_services():
    endpoints = ["http://192.168.1.80:2375"]

    mock_containers = [
        {
            "Names": ["/test-service"],
            "Image": "test-image:latest",
            "State": "running",
            "Ports": [
                {
                    "IP": "0.0.0.0",
                    "PublicPort": 8080,
                    "PrivatePort": 80,
                    "Type": "tcp"
                }
            ]
        },
        {
            "Names": ["/no-port-service"],
            "Image": "noport-image:latest",
            "State": "running",
            "Ports": []
        }
    ]

    responses.add(
        responses.GET,
        "http://192.168.1.80:2375/containers/json",
        json=mock_containers,
        status=200
    )

    services = homepage_sentry.discover_services(endpoints)
    assert len(services) == 2

    assert services[0]["name"] == "test-service"
    assert services[0]["image"] == "test-image:latest"
    assert services[0]["url"] == "http://192.168.1.80:8080"

    assert services[1]["name"] == "no-port-service"
    assert services[1]["url"] is None

@responses.activate
def test_probe_health():
    services = [
        {"name": "good-svc", "url": "http://example.com/good"},
        {"name": "bad-svc", "url": "http://example.com/bad"},
        {"name": "no-url-svc", "url": None}
    ]

    responses.add(responses.GET, "http://example.com/good", status=200)
    responses.add(responses.GET, "http://example.com/bad", status=500)

    results = homepage_sentry.probe_health(services)

    # Check results
    results_by_name = {s["name"]: s for s in results}
    assert results_by_name["good-svc"]["healthy"] is True
    assert results_by_name["bad-svc"]["healthy"] is False
    assert results_by_name["no-url-svc"]["healthy"] is False

def test_generate_config(tmp_path):
    services = [
        {"name": "test-svc", "image": "test-img", "url": "http://192.168.1.80:1234"},
        {"name": "no-url-svc", "image": "test-img2", "url": None}
    ]

    homepage_sentry.generate_config(services, output_dir=str(tmp_path))

    # Check services.yaml
    services_path = tmp_path / "services.yaml"
    assert services_path.exists()
    with open(services_path, "r") as f:
        services_data = yaml.safe_load(f)

    assert len(services_data) == 1
    assert "Discovered Services" in services_data[0]
    discovered = services_data[0]["Discovered Services"]
    assert len(discovered) == 1

    assert "test-svc" in discovered[0]
    assert discovered[0]["test-svc"]["href"] == "http://192.168.1.80:1234"
    assert discovered[0]["test-svc"]["description"] == "Image: test-img"

    # Check bookmarks.yaml
    bookmarks_path = tmp_path / "bookmarks.yaml"
    assert bookmarks_path.exists()
    with open(bookmarks_path, "r") as f:
        bookmarks_data = yaml.safe_load(f)

    assert "bookmarks" in bookmarks_data
    assert bookmarks_data["bookmarks"][0]["search"]["provider"] == "duckduckgo"

@patch('homepage_sentry.discover_services')
@patch('homepage_sentry.probe_health')
@patch('homepage_sentry.generate_config')
def test_run_cycle(mock_gen, mock_probe, mock_discover):
    # Mock dependencies
    mock_discover.return_value = [
        {"name": "test1"},
        {"name": "test2"}
    ]

    mock_probe.return_value = [
        {"name": "test1", "healthy": True},
        {"name": "test2", "healthy": False}
    ]

    # Mock args
    class Args:
        verify_tiles = True
        dry_run = False
        generate_config = True
        json = False

    args = Args()

    # Run cycle
    homepage_sentry.run_cycle(args)

    # Verify metrics updated
    total_services = homepage_sentry.homelab_homepage_services_total.collect()[0].samples[0].value
    assert total_services == 2.0

    ratio = homepage_sentry.homelab_homepage_healthy_services_ratio.collect()[0].samples[0].value
    assert ratio == 0.5

    mock_gen.assert_called_once()
