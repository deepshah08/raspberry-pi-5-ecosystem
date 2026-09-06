import os
import pytest
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
NGINX_CONF = PROJECT_DIR / "nginx.conf"
SCRIPT_PATH = PROJECT_DIR / "generate_pihole_rewrites.py"

def test_nginx_conf_exists():
    assert NGINX_CONF.exists(), "nginx.conf should exist"

def test_nginx_conf_contents():
    with open(NGINX_CONF, 'r') as f:
        content = f.read()

    # Required domains and their ports
    required_mappings = {
        'dash.home': '3030',
        'search.home': '8008',
        'briefing.home': '13378',
        'status.home': '3001',
        'metrics.home': '3000',
        'ai.home': '8000'
    }

    for domain, port in required_mappings.items():
        assert f"server_name {domain};" in content, f"{domain} server_name not found in nginx.conf"
        # The upstream port should exist
        assert f":{port};" in content, f"Port {port} for {domain} not found in nginx.conf"

    # Check for proxy headers and WebSocket support
    assert "proxy_set_header X-Forwarded-For" in content
    assert "proxy_set_header X-Real-IP" in content
    assert "proxy_set_header Upgrade $http_upgrade" in content
    assert "proxy_set_header Connection $connection_upgrade" in content
    assert "map $http_upgrade $connection_upgrade" in content
    assert "proxy_pass" in content

def test_generate_pihole_rewrites_dry_run():
    # Test dry-run execution
    result = subprocess.run(
        [str(SCRIPT_PATH), "--target-ip", "192.168.1.80", "--dry-run", "--nginx-conf", str(NGINX_CONF)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    output = result.stdout

    expected_domains = [
        "dash.home", "search.home", "briefing.home",
        "status.home", "metrics.home", "ai.home"
    ]

    for domain in expected_domains:
        assert f"192.168.1.80 {domain}" in output, f"Domain {domain} missing from script output"

def test_generate_pihole_rewrites_output_file(tmp_path):
    output_file = tmp_path / "custom.list"

    result = subprocess.run(
        [str(SCRIPT_PATH), "--target-ip", "192.168.1.80", "--output", str(output_file), "--nginx-conf", str(NGINX_CONF)],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    assert output_file.exists()

    with open(output_file, 'r') as f:
        content = f.read()

    expected_domains = [
        "dash.home", "search.home", "briefing.home",
        "status.home", "metrics.home", "ai.home"
    ]

    for domain in expected_domains:
        assert f"192.168.1.80 {domain}" in content, f"Domain {domain} missing from custom.list"
