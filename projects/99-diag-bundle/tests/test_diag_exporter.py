import sys
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diag_exporter import (
    get_docker_health,
    get_pihole_health,
    get_prometheus_health,
    get_systemd_health,
    get_storage_health,
    collect_health_metrics,
    package_bundle,
    parse_args
)

@pytest.fixture
def mock_subprocess_run():
    with patch('subprocess.run') as mock_run:
        yield mock_run

@pytest.fixture
def mock_urllib_request():
    with patch('urllib.request.urlopen') as mock_urlopen:
        yield mock_urlopen

def test_get_docker_health(mock_subprocess_run):
    mock_subprocess_run.return_value.stdout = '{"Names": "test-container", "State": "running", "Status": "Up 2 hours"}\n'
    result = get_docker_health()
    assert result['status'] == 'ok'
    assert len(result['containers']) == 1
    assert result['containers'][0]['name'] == 'test-container'

def test_get_pihole_health(mock_urllib_request):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"dns_queries_today": 100}'
    mock_urllib_request.return_value.__enter__.return_value = mock_response

    result = get_pihole_health()
    assert result['status'] == 'ok'
    assert result['metrics']['dns_queries_today'] == 100

def test_get_prometheus_health(mock_urllib_request):
    mock_response = MagicMock()
    mock_response.status = 200
    mock_urllib_request.return_value.__enter__.return_value = mock_response

    result = get_prometheus_health()
    assert result['status'] == 'ok'

def test_get_systemd_health(mock_subprocess_run):
    mock_subprocess_run.return_value.stdout = 'active\n'
    result = get_systemd_health()
    assert result['status'] == 'ok'
    assert result['services']['docker'] == 'active'

def test_get_storage_health_active(mock_subprocess_run):
    mock_subprocess_run.return_value.returncode = 0
    mock_subprocess_run.return_value.stdout = 'SMART overall-health self-assessment test result: PASSED\n'
    result = get_storage_health()
    assert result['status'] == 'ok'
    assert result['disks']['/dev/sda']['status'] == 'active'
    assert result['disks']['/dev/sda']['smart_passed'] is True

    # Verify disk safety (using -n standby)
    mock_subprocess_run.assert_any_call(
        ['smartctl', '-n', 'standby', '-a', '/dev/sda'],
        capture_output=True, text=True
    )

def test_get_storage_health_standby(mock_subprocess_run):
    mock_subprocess_run.return_value.returncode = 2
    mock_subprocess_run.return_value.stdout = 'Device is in STANDBY mode\n'
    result = get_storage_health()
    assert result['status'] == 'ok'
    assert result['disks']['/dev/sda']['status'] == 'standby'

def test_package_bundle(tmp_path):
    metrics = {"test": "data"}
    tar_path = package_bundle(metrics, str(tmp_path))

    assert Path(tar_path).exists()
    assert str(tar_path).endswith('.tar.gz')

    # Check sha256 manifest
    manifest_path = tar_path.replace('.tar.gz', '.sha256')
    assert Path(manifest_path).exists()

    with open(manifest_path, 'r') as f:
        manifest_content = f.read()
        assert '.tar.gz' in manifest_content
        # Check that hash is 64 characters long (sha256 hexdigest length)
        assert len(manifest_content.split()[0]) == 64

def test_parse_args():
    with patch('sys.argv', ['diag_exporter.py', '--collect-now', '--output-dir', '/tmp/test']):
        args = parse_args()
        assert args.collect_now is True
        assert args.output_dir == '/tmp/test'
        assert args.dry_run is False
        assert args.json is False
