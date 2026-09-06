import os
import yaml
import json
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_docker_compose_syntax():
    compose_file = os.path.join(BASE_DIR, 'docker-compose.yml')
    assert os.path.exists(compose_file), "docker-compose.yml does not exist"
    with open(compose_file, 'r') as f:
        compose_data = yaml.safe_load(f)

    assert 'services' in compose_data
    services = compose_data['services']

    # Check Prometheus
    assert 'prometheus' in services
    assert '9090:9090' in services['prometheus']['ports']
    assert any('/volume2/prometheus_data:/prometheus' in v for v in services['prometheus']['volumes'])

    # Check Grafana
    assert 'grafana' in services
    assert '3000:3000' in services['grafana']['ports']
    env = services['grafana'].get('environment', [])
    assert 'GF_SECURITY_ADMIN_PASSWORD=admin' in env
    assert 'GF_AUTH_ANONYMOUS_ENABLED=true' in env
    assert 'GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer' in env

    # Check Node Exporter
    assert 'node-exporter' in services
    assert '9100:9100' in services['node-exporter']['ports']
    volumes = services['node-exporter']['volumes']
    assert '/proc:/host/proc:ro' in volumes
    assert '/sys:/host/sys:ro' in volumes

def test_prometheus_config():
    prom_file = os.path.join(BASE_DIR, 'prometheus', 'prometheus.yml')
    assert os.path.exists(prom_file), "prometheus.yml does not exist"
    with open(prom_file, 'r') as f:
        prom_data = yaml.safe_load(f)

    assert prom_data['global']['scrape_interval'] == '15s'
    assert prom_data['global']['evaluation_interval'] == '15s'

    jobs = {job['job_name']: job['static_configs'][0]['targets'][0] for job in prom_data['scrape_configs']}

    assert jobs.get('nas_node') == '192.168.1.80:9100'
    assert jobs.get('pi5_node') == '192.168.1.92:9100'
    assert jobs.get('uptime_kuma') == '192.168.1.80:3001'
    assert jobs.get('cadvisor') == '192.168.1.80:8080'
    assert jobs.get('pihole') == '192.168.1.80:9617'

def test_grafana_dashboard_json():
    dash_file = os.path.join(BASE_DIR, 'grafana', 'dashboards', 'homelab_overview.json')
    assert os.path.exists(dash_file), "homelab_overview.json does not exist"
    with open(dash_file, 'r') as f:
        dash_data = json.load(f)

    panels = dash_data.get('panels', [])
    panel_titles = [p.get('title') for p in panels]

    assert "CPU Thermals (Intel N100 vs Pi 5)" in panel_titles
    assert "NVMe IOPS & Disk Utilization" in panel_titles
    assert "RAM Allocation" in panel_titles
    assert "Pi-hole Query Rates" in panel_titles
    assert "Container Health" in panel_titles

    # Verify target expressions
    expressions = []
    for p in panels:
        for t in p.get('targets', []):
            expressions.append(t.get('expr'))

    assert "node_hwmon_temp_celsius" in expressions
    assert "rate(pihole_dns_queries_today[5m])" in expressions
    assert "sum(up{job=\"cadvisor\"})" in expressions
    assert any("node_memory_MemAvailable_bytes" in e for e in expressions)
    assert any("node_disk_reads_completed_total" in e for e in expressions)
