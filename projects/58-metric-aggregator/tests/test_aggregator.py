import sys
from pathlib import Path
import json
import yaml
from unittest.mock import patch, mock_open, MagicMock

# Ensure standalone test execution works by appending project dir to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregator import probe_target, discover_targets, generate_yaml_config, generate_json_config, EXPORTER_REGISTRY

@patch("aggregator.requests.get")
def test_probe_target_success(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_get.return_value = mock_response

    assert probe_target("127.0.0.1:9090") is True
    # Should only call /metrics because it succeeds on first try
    mock_get.assert_called_once_with("http://127.0.0.1:9090/metrics", timeout=2.0)

@patch("aggregator.requests.get")
def test_probe_target_fallback_success(mock_get):
    # First response fails, second succeeds
    fail_response = MagicMock()
    fail_response.status_code = 404
    success_response = MagicMock()
    success_response.status_code = 200
    mock_get.side_effect = [fail_response, success_response]

    assert probe_target("127.0.0.1:9090") is True
    assert mock_get.call_count == 2

@patch("aggregator.requests.get")
def test_probe_target_failure(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response

    assert probe_target("127.0.0.1:9090") is False
    assert mock_get.call_count == 2

@patch("aggregator.probe_target")
def test_discover_targets(mock_probe):
    # Only return true for one specific target to test filtering
    def mock_probe_logic(target):
        return target == "192.168.1.80:9100"

    mock_probe.side_effect = mock_probe_logic

    configs = discover_targets()

    # We should have exactly one job in the output
    assert len(configs) == 1
    assert configs[0]["job_name"] == "node_exporter"
    assert configs[0]["targets"] == ["192.168.1.80:9100"]

@patch("builtins.open", new_callable=mock_open)
def test_generate_yaml_config(mock_file):
    active_configs = [
        {"job_name": "test_job", "targets": ["10.0.0.1:1234"]}
    ]
    generate_yaml_config(active_configs, "test.yml")

    # Get all the writes
    handle = mock_file()
    written_data = "".join(call.args[0] for call in handle.write.call_args_list)

    parsed = yaml.safe_load(written_data)
    assert parsed["global"]["scrape_interval"] == "15s"
    assert len(parsed["scrape_configs"]) == 1
    assert parsed["scrape_configs"][0]["job_name"] == "test_job"
    assert parsed["scrape_configs"][0]["static_configs"][0]["targets"] == ["10.0.0.1:1234"]

@patch("builtins.open", new_callable=mock_open)
def test_generate_json_config(mock_file):
    active_configs = [
        {"job_name": "test_job", "targets": ["10.0.0.1:1234"]}
    ]
    generate_json_config(active_configs, "test.json")

    handle = mock_file()
    written_data = "".join(call.args[0] for call in handle.write.call_args_list)

    parsed = json.loads(written_data)
    assert len(parsed) == 1
    assert parsed[0]["targets"] == ["10.0.0.1:1234"]
    assert parsed[0]["labels"]["job"] == "test_job"

@patch("sys.argv", ["aggregator.py", "--output", "dummy.json", "--format", "json", "--dry-run"])
@patch("aggregator.discover_targets")
def test_cli_dry_run(mock_discover):
    mock_discover.return_value = [{"job_name": "test", "targets": ["1.2.3.4:123"]}]
    from aggregator import main
    main()
    mock_discover.assert_called_once()

@patch("sys.argv", ["aggregator.py", "--output", "dummy.yml", "--format", "yaml"])
@patch("aggregator.discover_targets")
@patch("aggregator.generate_yaml_config")
def test_cli_generate_yaml(mock_generate, mock_discover):
    mock_discover.return_value = [{"job_name": "test", "targets": ["1.2.3.4:123"]}]
    from aggregator import main
    main()
    mock_discover.assert_called_once()
    mock_generate.assert_called_once_with([{"job_name": "test", "targets": ["1.2.3.4:123"]}], "dummy.yml")
