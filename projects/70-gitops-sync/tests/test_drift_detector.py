import sys
from pathlib import Path

# Add the parent directory to sys.path so we can import drift_detector
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from unittest.mock import MagicMock, patch
import pytest

from drift_detector import (
    ComposeParser,
    RuntimeInspector,
    DriftComparator,
    ReportGenerator,
)


@pytest.fixture
def mock_compose_data():
    return {
        "service-a": {
            "image": "my-image:v1.0",
            "ports": ["8080:80"],
            "volumes": ["./data:/app/data"],
            "environment": {"ENV_VAR": "value1"}
        }
    }


@pytest.fixture
def mock_runtime_data():
    return {
        "service-a": {
            "image": "my-image:v1.0",
            "ports": ["8080:80"],
            "volumes": ["/absolute/path/data:/app/data"],
            "environment": {"ENV_VAR": "value1", "OTHER": "value2"}
        }
    }


def test_compose_parser_volumes_ports():
    parser = ComposeParser(".")
    # Test internal parsing logic
    assert parser._parse_ports([{"published": 8080, "target": 80}]) == ["8080:80"]
    assert parser._parse_ports(["8080:80"]) == ["8080:80"]
    
    assert parser._parse_volumes([{"source": "./data", "target": "/app/data"}]) == ["./data:/app/data"]
    assert parser._parse_volumes(["./data:/app/data"]) == ["./data:/app/data"]


def test_clean_state_no_drift(mock_compose_data, mock_runtime_data):
    comparator = DriftComparator(mock_compose_data, mock_runtime_data)
    reports = comparator.compare()
    assert len(reports) == 0


def test_image_tag_mismatch(mock_compose_data, mock_runtime_data):
    mock_runtime_data["service-a"]["image"] = "my-image:latest"
    comparator = DriftComparator(mock_compose_data, mock_runtime_data)
    reports = comparator.compare()
    assert len(reports) == 1
    assert reports[0]["drift_type"] == "image_mismatch"
    assert reports[0]["expected"] == "my-image:v1.0"
    assert reports[0]["actual"] == "my-image:latest"


def test_port_discrepancy(mock_compose_data, mock_runtime_data):
    mock_runtime_data["service-a"]["ports"] = ["9090:80"]
    comparator = DriftComparator(mock_compose_data, mock_runtime_data)
    reports = comparator.compare()
    assert len(reports) == 1
    assert reports[0]["drift_type"] == "port_mismatch"
    assert reports[0]["expected"] == ["8080:80"]
    assert reports[0]["actual"] == ["9090:80"]


def test_volume_difference(mock_compose_data, mock_runtime_data):
    mock_runtime_data["service-a"]["volumes"] = ["/absolute/path/data:/wrong/dest"]
    comparator = DriftComparator(mock_compose_data, mock_runtime_data)
    reports = comparator.compare()
    assert len(reports) == 1
    assert reports[0]["drift_type"] == "volume_mismatch"
    # destinations should be compared
    assert set(reports[0]["expected"]) == {"/app/data"}
    assert set(reports[0]["actual"]) == {"/wrong/dest"}


def test_missing_service(mock_compose_data):
    mock_runtime_data = {} # No running services
    comparator = DriftComparator(mock_compose_data, mock_runtime_data)
    reports = comparator.compare()
    assert len(reports) == 1
    assert reports[0]["drift_type"] == "missing_service"


def test_environment_mismatch(mock_compose_data, mock_runtime_data):
    mock_runtime_data["service-a"]["environment"]["ENV_VAR"] = "wrong_value"
    comparator = DriftComparator(mock_compose_data, mock_runtime_data)
    reports = comparator.compare()
    assert len(reports) == 1
    assert reports[0]["drift_type"] == "env_mismatch"


def test_report_generator():
    reports = [{
        "service": "test-service",
        "drift_type": "image_mismatch",
        "expected": "v1",
        "actual": "v2"
    }]
    gen = ReportGenerator(reports)
    
    json_out = json.loads(gen.to_json())
    assert len(json_out) == 1
    assert json_out[0]["service"] == "test-service"
    
    md_out = gen.to_markdown()
    assert "Configuration Drift Detected!" in md_out
    assert "test-service" in md_out

    gen_clean = ReportGenerator([])
    md_clean = gen_clean.to_markdown()
    assert "No Drift Detected" in md_clean


@patch("drift_detector.docker")
def test_runtime_inspector_mock(mock_docker):
    # Setup mock docker container
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.name = "my_container"
    mock_container.labels = {"com.docker.compose.service": "mock-service"}
    mock_container.image.tags = ["mock-image:1.0"]
    mock_container.attrs = {
        "Config": {"Env": ["VAR=1"]},
        "HostConfig": {"PortBindings": {"80/tcp": [{"HostPort": "8080"}]}},
        "Mounts": [{"Source": "/host/dir", "Destination": "/container/dir"}]
    }
    mock_client.containers.list.return_value = [mock_container]
    
    inspector = RuntimeInspector(mock_client=mock_client)
    state = inspector.get_running_state()
    
    assert "mock-service" in state
    assert state["mock-service"]["image"] == "mock-image:1.0"
    assert state["mock-service"]["ports"] == ["8080:80"]
    assert state["mock-service"]["volumes"] == ["/host/dir:/container/dir"]
    assert state["mock-service"]["environment"] == {"VAR": "1"}


@patch("sys.argv", ["drift_detector.py", "--check-now", "--json", "--repo-root", "/tmp"])
@patch("drift_detector.ComposeParser")
@patch("drift_detector.RuntimeInspector")
@patch("drift_detector.DriftComparator")
@patch("drift_detector.ReportGenerator")
def test_cli_arguments(mock_report_gen, mock_drift_comp, mock_inspector, mock_compose_parser):
    from drift_detector import main
    # Ensure components are correctly instantiated with CLI args
    mock_compose_parser_instance = mock_compose_parser.return_value
    mock_inspector_instance = mock_inspector.return_value
    mock_drift_comp_instance = mock_drift_comp.return_value
    mock_report_gen_instance = mock_report_gen.return_value
    
    mock_compose_parser_instance.parse.return_value = {}
    mock_inspector_instance.get_running_state.return_value = {}
    mock_drift_comp_instance.compare.return_value = []
    
    main()
    
    mock_compose_parser.assert_called_with("/tmp")
    mock_report_gen_instance.to_json.assert_called_once()
