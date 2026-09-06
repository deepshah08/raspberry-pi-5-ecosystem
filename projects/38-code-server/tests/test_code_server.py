import os
import yaml
import pytest
from unittest.mock import patch, MagicMock
import subprocess
import urllib.error

# Import the init_workspace module
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import init_workspace

@pytest.fixture
def compose_config():
    compose_path = os.path.join(os.path.dirname(__file__), '..', 'docker-compose.yml')
    with open(compose_path, 'r') as f:
        return yaml.safe_load(f)

def test_compose_structure(compose_config):
    assert 'services' in compose_config
    assert 'code-server' in compose_config['services']

    code_server = compose_config['services']['code-server']

    # Check ports
    assert 'ports' in code_server
    ports = code_server['ports']
    assert any('8443:8443' in str(port) for port in ports)

    # Check volumes
    assert 'volumes' in code_server
    volumes = code_server['volumes']
    assert any('./workspace' in v for v in volumes)
    assert any('./git-configs' in v for v in volumes)
    assert any('./extensions' in v for v in volumes)

    # Check env vars
    assert 'environment' in code_server
    env_vars = code_server['environment']
    env_str = str(env_vars)
    assert 'PUID=${UID:-1000}' in env_str or 'PUID=' in env_str
    assert 'PGID=${GID:-1000}' in env_str or 'PGID=' in env_str
    assert 'PASSWORD=' in env_str
    assert 'HASH=' in env_str
    assert 'SUDO_PASSWORD=' in env_str

@patch('init_workspace.subprocess.run')
def test_configure_git_user_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    result = init_workspace.configure_git_user("Test User", "test@example.com")
    assert result is True
    assert mock_run.call_count == 2
    mock_run.assert_any_call(["git", "config", "--global", "user.name", "Test User"], check=True)
    mock_run.assert_any_call(["git", "config", "--global", "user.email", "test@example.com"], check=True)

@patch('init_workspace.subprocess.run')
def test_configure_git_user_failure(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(1, 'git')
    result = init_workspace.configure_git_user("Test User", "test@example.com")
    assert result is False

@patch('init_workspace.os.path.exists')
@patch('init_workspace.os.listdir')
@patch('init_workspace.subprocess.run')
def test_clone_repository_empty_dir(mock_run, mock_listdir, mock_exists):
    mock_exists.return_value = False
    mock_run.return_value = MagicMock(returncode=0)
    result = init_workspace.clone_repository("http://repo", "/dest")
    assert result is True
    mock_run.assert_called_once_with(["git", "clone", "http://repo", "/dest"], check=True)

@patch('init_workspace.os.path.exists')
@patch('init_workspace.os.listdir')
@patch('init_workspace.subprocess.run')
def test_clone_repository_existing_dir(mock_run, mock_listdir, mock_exists):
    mock_exists.return_value = True
    mock_listdir.return_value = ['file1']
    result = init_workspace.clone_repository("http://repo", "/dest")
    assert result is True
    mock_run.assert_not_called()

@patch('init_workspace.os.path.exists')
@patch('init_workspace.subprocess.run')
def test_setup_python_venv_new(mock_run, mock_exists):
    mock_exists.return_value = False
    mock_run.return_value = MagicMock(returncode=0)
    result = init_workspace.setup_python_venv("/venv")
    assert result is True
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0][1:] == ["-m", "venv", "/venv"]

@patch('init_workspace.os.path.exists')
@patch('init_workspace.subprocess.run')
def test_setup_python_venv_existing(mock_run, mock_exists):
    mock_exists.return_value = True
    result = init_workspace.setup_python_venv("/venv")
    assert result is True
    mock_run.assert_not_called()

@patch('init_workspace.urllib.request.urlopen')
def test_check_connectivity_success(mock_urlopen):
    mock_urlopen.return_value = MagicMock()
    result = init_workspace.check_connectivity()
    assert result is True

@patch('init_workspace.urllib.request.urlopen')
def test_check_connectivity_failure(mock_urlopen):
    mock_urlopen.side_effect = urllib.error.URLError("Network unreachable")
    result = init_workspace.check_connectivity()
    assert result is False
