import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock, patch
import json
import argparse

from runner_manager import GitHubClient, DockerClient, RunnerManager, main

@pytest.fixture
def mock_github_client():
    client = MagicMock(spec=GitHubClient)
    client.repo = "owner/repo"
    return client

@pytest.fixture
def mock_docker_client():
    client = MagicMock(spec=DockerClient)
    return client

def test_github_client_list_runners(mocker):
    mocker.patch('requests.get')
    import requests
    mock_response = MagicMock()
    mock_response.json.return_value = {'runners': [{'id': 1, 'name': 'runner-1', 'status': 'online'}]}
    requests.get.return_value = mock_response

    client = GitHubClient("token", "owner/repo")
    runners = client.list_runners()
    assert len(runners) == 1
    assert runners[0]['name'] == 'runner-1'

def test_github_client_remove_runner(mocker):
    mocker.patch('requests.delete')
    import requests
    mock_response = MagicMock()
    requests.delete.return_value = mock_response

    client = GitHubClient("token", "owner/repo")
    assert client.remove_runner(1) == True

def test_github_client_get_registration_token(mocker):
    mocker.patch('requests.post')
    import requests
    mock_response = MagicMock()
    mock_response.json.return_value = {'token': 'mock-token'}
    requests.post.return_value = mock_response

    client = GitHubClient("token", "owner/repo")
    assert client.get_registration_token() == 'mock-token'

def test_docker_client_list_runner_containers(mocker):
    mocker.patch('docker.from_env')
    import docker
    mock_client = MagicMock()
    docker.from_env.return_value = mock_client

    mock_container = MagicMock()
    mock_container.name = "gh-runner-1"
    mock_client.containers.list.return_value = [mock_container]

    client = DockerClient()
    containers = client.list_runner_containers()
    assert len(containers) == 1
    assert containers[0].name == "gh-runner-1"

def test_docker_client_remove_container(mocker):
    mocker.patch('docker.from_env')
    import docker
    mock_client = MagicMock()
    docker.from_env.return_value = mock_client

    mock_container = MagicMock()
    mock_client.containers.get.return_value = mock_container

    client = DockerClient()
    assert client.remove_container("mock-id") == True
    mock_container.remove.assert_called_once_with(force=True)

def test_docker_client_start_runner(mocker):
    mocker.patch('docker.from_env')
    import docker
    mock_client = MagicMock()
    docker.from_env.return_value = mock_client

    client = DockerClient()
    assert client.start_runner("owner/repo", "token", "runner-name") == True
    mock_client.containers.run.assert_called_once()

def test_runner_manager_audit(mock_github_client, mock_docker_client):
    # Setup mocks
    mock_github_client.list_runners.return_value = [
        {'id': 1, 'name': 'runner-1', 'status': 'online'},
        {'id': 2, 'name': 'runner-2', 'status': 'offline'}
    ]
    mock_github_client.remove_runner.return_value = True

    mock_container_1 = MagicMock()
    mock_container_1.name = "container-1"
    mock_container_1.id = "c1"
    mock_container_1.status = "running"
    mock_container_1.stats.return_value = {'memory_stats': {'usage': 2 * 1024 * 1024 * 1024}} # 2GB

    mock_container_2 = MagicMock()
    mock_container_2.name = "container-2"
    mock_container_2.id = "c2"
    mock_container_2.status = "exited"

    mock_docker_client.list_runner_containers.return_value = [mock_container_1, mock_container_2]
    mock_docker_client.remove_container.return_value = True

    manager = RunnerManager(mock_github_client, mock_docker_client, max_runners=3, dry_run=False)
    report = manager.audit()

    # Assertions
    assert "runner-1" in report["github_runners"]
    assert "container-1" in report["docker_containers"]

    # Check actions
    actions = report["actions_taken"]
    assert "Removed offline GitHub runner: runner-2" in actions
    assert "Removed dead container: container-2" in actions
    assert "Removed high-memory container: container-1" in actions

    mock_github_client.remove_runner.assert_called_once_with(2)
    assert mock_docker_client.remove_container.call_count == 2

def test_runner_manager_scale_up(mock_github_client, mock_docker_client):
    mock_github_client.list_runners.return_value = [
        {'id': 1, 'name': 'runner-1', 'status': 'online'}
    ]
    mock_github_client.get_registration_token.return_value = "token"
    mock_docker_client.start_runner.return_value = True

    manager = RunnerManager(mock_github_client, mock_docker_client, max_runners=3, dry_run=False)
    report = manager.scale()

    # Expect 2 runners to start
    actions = report["actions_taken"]
    assert len(actions) == 2
    assert "Started new runner container" in actions[0]
    assert mock_docker_client.start_runner.call_count == 2

def test_runner_manager_scale_down_or_maintain(mock_github_client, mock_docker_client):
    mock_github_client.list_runners.return_value = [
        {'id': 1, 'name': 'runner-1', 'status': 'online'},
        {'id': 2, 'name': 'runner-2', 'status': 'online'},
        {'id': 3, 'name': 'runner-3', 'status': 'online'}
    ]

    manager = RunnerManager(mock_github_client, mock_docker_client, max_runners=2, dry_run=False)
    report = manager.scale()

    actions = report["actions_taken"]
    assert len(actions) == 0
    mock_docker_client.start_runner.assert_not_called()

def test_runner_manager_dry_run(mock_github_client, mock_docker_client):
    mock_github_client.list_runners.return_value = [
        {'id': 2, 'name': 'runner-2', 'status': 'offline'}
    ]
    mock_docker_client.list_runner_containers.return_value = []

    manager = RunnerManager(mock_github_client, mock_docker_client, max_runners=1, dry_run=True)
    report = manager.audit()

    actions = report["actions_taken"]
    assert "[DRY-RUN] Would remove offline GitHub runner: runner-2" in actions
    mock_github_client.remove_runner.assert_not_called()

def test_main_cli(mocker, capsys):
    mocker.patch('sys.argv', ['runner_manager.py', '--repo', 'test/repo', '--audit-now', '--json'])

    mocker.patch('runner_manager.GitHubClient')
    mocker.patch('runner_manager.DockerClient')

    mock_manager = MagicMock()
    mock_manager.audit.return_value = {"actions_taken": ["audit_action"]}
    mock_manager.scale.return_value = {"actions_taken": ["scale_action"]}

    mocker.patch('runner_manager.RunnerManager', return_value=mock_manager)

    main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert "audit" in output
    assert "scale" in output
    assert output["audit"]["actions_taken"] == ["audit_action"]
    assert output["scale"]["actions_taken"] == ["scale_action"]
