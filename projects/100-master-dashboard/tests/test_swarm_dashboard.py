import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest
import io
from fastapi.testclient import TestClient
from contextlib import redirect_stdout
from swarm_cli import do_status, do_check, do_audit, do_export_matrix, MOCK_MATRIX
from dashboard_server import app

def test_cli_status():
    f = io.StringIO()
    with redirect_stdout(f):
        do_status(as_json=True)
    out = f.getvalue()
    data = json.loads(out)
    assert data["status"] == "ok"
    assert "services" in data
    assert len(data["services"]) == len(MOCK_MATRIX["projects"])

def test_cli_check():
    f = io.StringIO()
    with redirect_stdout(f):
        do_check(as_json=True)
    out = f.getvalue()
    data = json.loads(out)
    assert data["tests_passed"] == 5
    assert data["tests_failed"] == 0

def test_cli_audit():
    f = io.StringIO()
    with redirect_stdout(f):
        do_audit(as_json=True)
    out = f.getvalue()
    data = json.loads(out)
    assert data["status"] == "PASS"
    assert "invariants" in data
    assert "dhcp_option_6" in data["invariants"]

def test_cli_export_matrix_json(tmp_path):
    p = tmp_path / "matrix.json"
    do_export_matrix(str(p))
    content = json.loads(p.read_text())
    assert "projects" in content
    assert len(content["projects"]) == len(MOCK_MATRIX["projects"])

client = TestClient(app)

def test_dashboard_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Homelab Master Unified Orchestration Dashboard" in response.text
    assert "UGREEN NAS" in response.text
    assert "Raspberry Pi 5" in response.text

def test_dashboard_api_matrix():
    response = client.get("/api/matrix")
    assert response.status_code == 200
    data = response.json()
    assert "projects" in data
    assert len(data["projects"]) == len(MOCK_MATRIX["projects"])

def test_dashboard_api_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["cluster_health"] == "ok"
    assert "invariants" in data
    assert data["invariants"]["dhcp_option_6"] == "PASS"

def test_dashboard_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "homelab_swarm_projects_total" in response.text
    assert "homelab_swarm_audit_passing" in response.text
    assert "homelab_swarm_tier_compliance_ratio" in response.text
