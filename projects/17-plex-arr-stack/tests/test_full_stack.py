import os
import json
import yaml
import pytest
import socket
from unittest.mock import patch, MagicMock
import sys
import subprocess

# Add scripts and config dirs to sys.path to allow importing modules
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(BASE_DIR, 'config'))
sys.path.insert(0, os.path.join(BASE_DIR, 'scripts'))


def test_docker_compose_yml():
    compose_path = os.path.join(BASE_DIR, 'docker-compose.yml')
    assert os.path.exists(compose_path), "docker-compose.yml does not exist"
    
    with open(compose_path, 'r') as f:
        data = yaml.safe_load(f)
        
    services = data.get('services', {})
    
    # Test: all 9 services present
    expected_services = {'plex', 'gluetun', 'qbittorrent', 'prowlarr', 'radarr', 'sonarr', 'bazarr', 'overseerr', 'tautulli'}
    for srv in expected_services:
        assert srv in services, f"Service {srv} missing"
        
    # Test: qbittorrent has network_mode: 'service:gluetun'
    assert services['qbittorrent'].get('network_mode') == 'service:gluetun'
    
    # Test: plex has network_mode: host
    assert services['plex'].get('network_mode') == 'host'
    
    # Test: gluetun has NET_ADMIN cap_add
    assert 'NET_ADMIN' in services['gluetun'].get('cap_add', [])
    
    # Test: radarr/sonarr/bazarr/qbittorrent volumes include /data
    for srv in ['radarr', 'sonarr', 'bazarr', 'qbittorrent']:
        volumes = services[srv].get('volumes', [])
        assert any('/data' in vol for vol in volumes), f"{srv} missing /data volume mapping"
        
    # Test: all services have restart: unless-stopped
    for srv_name, srv_config in services.items():
        assert srv_config.get('restart') == 'unless-stopped'
        
    # Test: all services (except gluetun which is non-linuxserver) have PUID/PGID env vars
    for srv_name, srv_config in services.items():
        if srv_name == 'gluetun':
            continue
        env = srv_config.get('environment', [])
        if isinstance(env, list):
            env_keys = [e.split('=')[0] for e in env]
        else:
            env_keys = list(env.keys())
        assert 'PUID' in env_keys, f"{srv_name} missing PUID"
        assert 'PGID' in env_keys, f"{srv_name} missing PGID"


def test_env_template():
    env_path = os.path.join(BASE_DIR, '.env.template')
    assert os.path.exists(env_path), ".env.template does not exist"
    
    with open(env_path, 'r') as f:
        content = f.read()
        
    env_vars = {}
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            if '=' in line:
                key, val = line.split('=', 1)
                val = val.split('#')[0].strip()
                env_vars[key.strip()] = val
                
    # Test: all required keys are present
    required_keys = ['PUID', 'PGID', 'TZ', 'MEDIA_PATH', 'CONFIG_PATH', 'PLEX_CLAIM', 'VPN_SERVICE_PROVIDER', 'OPENVPN_USER', 'OPENVPN_PASSWORD']
    for k in required_keys:
        assert k in env_vars, f"Missing required env var: {k}"
        
    # Test default values
    assert env_vars.get('PUID') == '1000'
    assert env_vars.get('TZ') == 'America/Los_Angeles'
    assert env_vars.get('MEDIA_PATH') == '/mnt/nas/media'
    assert env_vars.get('CONFIG_PATH') == '/mnt/nas/configs'


def test_custom_formats():
    for app in ['radarr', 'sonarr']:
        path = os.path.join(BASE_DIR, 'config', f'{app}_custom_formats.json')
        assert os.path.exists(path), f"{path} does not exist"
        
        with open(path, 'r') as f:
            data = json.load(f)
            
        # Contains exactly 5 formats
        assert len(data) == 5
        
        # Format names
        expected_names = {'Hindi Audio', 'Dual Audio', 'Hindi Dubbed', 'English Audio', 'Non EN-HI Audio'}
        actual_names = {fmt.get('name') for fmt in data}
        assert actual_names == expected_names
        
        for fmt in data:
            assert 'name' in fmt
            assert 'specifications' in fmt
            
            for spec in fmt['specifications']:
                assert 'implementation' in spec
                assert 'fields' in spec
                
                # Hindi Audio regex contains 'Hindi'
                if fmt['name'] == 'Hindi Audio':
                    has_hindi = False
                    for field in spec['fields']:
                        if isinstance(field.get('value'), str) and 'Hindi' in field.get('value'):
                            has_hindi = True
                    assert has_hindi, "Hindi Audio specifications must contain 'Hindi'"


@patch('requests.get')
@patch('requests.post')
@patch('requests.put')
def test_radarr_apply_config(mock_put, mock_post, mock_get):
    try:
        import radarr_apply_config
    except ImportError:
        pytest.skip("radarr_apply_config module not found")
        
    apply_fn = getattr(radarr_apply_config, 'apply', getattr(radarr_apply_config, 'main', None))
    assert apply_fn is not None, "radarr_apply_config must have an apply or main function"
    
    # Mock requests.get to return empty list (no existing formats)
    mock_get.return_value.json.return_value = []
    mock_get.return_value.status_code = 200
    
    # Mock requests.post to return {id: 1}
    mock_post.return_value.json.return_value = {'id': 1}
    mock_post.return_value.status_code = 201
    
    os.environ['RADARR_API_KEY'] = 'fake_key'
    
    # Import and call apply function
    apply_fn()
    
    # Test: POST called 5 times (once per format)
    assert mock_post.call_count == 5
    assert mock_put.call_count == 0
    
    # Test: when format already exists, PUT is called instead of POST
    mock_post.reset_mock()
    mock_put.reset_mock()
    
    mock_get.return_value.json.return_value = [
        {'name': 'Hindi Audio', 'id': 1},
        {'name': 'Dual Audio', 'id': 2},
        {'name': 'Hindi Dubbed', 'id': 3},
        {'name': 'English Audio', 'id': 4},
        {'name': 'Non EN-HI Audio', 'id': 5}
    ]
    mock_put.return_value.status_code = 202
    
    apply_fn()
    assert mock_put.call_count == 5
    assert mock_post.call_count == 0
    
    # Test: missing RADARR_API_KEY raises SystemExit or prints error
    del os.environ['RADARR_API_KEY']
    mock_get.reset_mock()
    try:
        apply_fn()
    except SystemExit:
        pass
    assert mock_get.call_count == 0


@patch('socket.socket')
@patch('os.path.exists')
def test_validate_stack(mock_exists, mock_socket_class):
    try:
        import validate_stack
    except ImportError:
        pytest.skip("validate_stack module not found")
        
    mock_sock = MagicMock()
    mock_socket_class.return_value = mock_sock
    mock_socket_class.return_value.__enter__.return_value = mock_sock
    
    # Mock os.path.exists to return True
    mock_exists.return_value = True
    
    # Mock socket.connect_ex to return 0 (success) for all ports
    mock_sock.connect_ex.return_value = 0
    
    # Test: all_pass returns True when all ports open
    if hasattr(validate_stack, 'all_pass'):
        assert validate_stack.all_pass() is True
    else:
        assert validate_stack.check_port("localhost", 7878) is True
    
    # Mock socket.connect_ex to return 1 (failure) for port 7878
    def side_effect_connect(address):
        if address[1] == 7878:
            return 1
        return 0
    mock_sock.connect_ex.side_effect = side_effect_connect
    
    # Test: all_pass returns False, radarr shown as down
    if hasattr(validate_stack, 'all_pass'):
        assert validate_stack.all_pass() is False
    else:
        assert validate_stack.check_port("localhost", 7878) is False
    
    # Mock os.path.exists to return False for /mnt/nas/media
    mock_sock.connect_ex.side_effect = None
    mock_sock.connect_ex.return_value = 0
    def side_effect_exists(path):
        if path == '/mnt/nas/media':
            return False
        return True
    mock_exists.side_effect = side_effect_exists
    
    # Test: NAS path check fails correctly
    if hasattr(validate_stack, 'all_pass'):
        assert validate_stack.all_pass() is False
    else:
        assert validate_stack.check_path('/mnt/nas/media') is False


def test_init_nas_dirs():
    path = os.path.join(BASE_DIR, 'scripts', 'init_nas_dirs.sh')
    assert os.path.exists(path), "init_nas_dirs.sh does not exist"
    
    with open(path, 'r') as f:
        content = f.read()
    lines = content.splitlines()
    
    # Test: script has bash shebang
    assert lines[0] == '#!/bin/bash'
    
    # Test: script contains 'mkdir -p'
    assert 'mkdir -p' in content
    
    # Test: script contains /mnt/nas/media/movies
    assert '/mnt/nas/media/movies' in content
    
    # Test: script contains /mnt/nas/configs
    assert '/mnt/nas/configs' in content
    
    # Test: script is not empty (> 10 lines)
    assert len(lines) > 10


def test_first_run_setup():
    path = os.path.join(BASE_DIR, 'scripts', 'first_run_setup.sh')
    assert os.path.exists(path), "first_run_setup.sh does not exist"
    
    with open(path, 'r') as f:
        content = f.read()
    lines = content.splitlines()
    
    # Test: has shebang
    assert lines[0].startswith('#!')
    
    # Test: contains 'docker compose up'
    assert 'docker compose up' in content
    
    # Test: contains 'validate_env.py'
    assert 'validate_env.py' in content
    
    # Test: contains 'init_nas_dirs.sh'
    assert 'init_nas_dirs.sh' in content
    
    # Test: contains 'validate_stack.py'
    assert 'validate_stack.py' in content
