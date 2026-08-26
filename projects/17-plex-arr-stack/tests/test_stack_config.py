import os
import sys
import subprocess
from unittest import mock
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
import validate_stack

def test_validate_stack_all_pass(capsys):
    with mock.patch("validate_stack.socket.socket") as mock_socket, \
         mock.patch("validate_stack.os.path.exists") as mock_exists, \
         mock.patch("validate_stack.subprocess.run") as mock_run:
        
        # Mock port check to return 0 (success)
        mock_socket_instance = mock_socket.return_value.__enter__.return_value
        mock_socket_instance.connect_ex.return_value = 0
        
        # Mock path check to return True (exists)
        mock_exists.return_value = True
        
        # Mock docker check
        mock_run.return_value = mock.Mock(returncode=0)
        
        # Run main and catch SystemExit
        with pytest.raises(SystemExit) as excinfo:
            validate_stack.main()
            
        assert excinfo.value.code == 0
        
        captured = capsys.readouterr()
        assert "All checks passed! ✅" in captured.out
        assert "Plex            | 32400  | ✅" in captured.out

def test_validate_stack_one_fail(capsys):
    with mock.patch("validate_stack.socket.socket") as mock_socket, \
         mock.patch("validate_stack.os.path.exists") as mock_exists, \
         mock.patch("validate_stack.subprocess.run") as mock_run:
        
        # Mock port check - make one fail
        mock_socket_instance = mock_socket.return_value.__enter__.return_value
        
        def mock_connect_ex(address):
            if address[1] == 32400: # Plex
                return 1 # fail
            return 0 # success
            
        mock_socket_instance.connect_ex.side_effect = mock_connect_ex
        
        # Mock path check
        mock_exists.return_value = True
        
        # Mock docker check
        mock_run.return_value = mock.Mock(returncode=0)
        
        with pytest.raises(SystemExit) as excinfo:
            validate_stack.main()
            
        assert excinfo.value.code == 1
        
        captured = capsys.readouterr()
        assert "Some checks failed! ❌" in captured.out
        assert "Plex            | 32400  | ❌" in captured.out
        assert "Radarr          | 7878   | ✅" in captured.out

def test_env_template():
    env_template_path = os.path.join(os.path.dirname(__file__), '../.env.template')
    if os.path.exists(env_template_path):
        with open(env_template_path, 'r') as f:
            content = f.read()
            assert 'PUID' in content or 'PGID' in content or 'TZ' in content
    else:
        pass

def test_init_nas_dirs_script():
    script_path = os.path.join(os.path.dirname(__file__), '../scripts/init_nas_dirs.sh')
    
    assert os.path.exists(script_path), f"Script not found at {script_path}"
    
    with open(script_path, 'r') as f:
        content = f.read()
        
    assert content.startswith('#!/bin/bash'), "Script must have bash shebang"
    assert "mkdir -p" in content, "Script must use mkdir -p to create directories"
    assert "chown 1000:1000" in content, "Script must set ownership to 1000:1000"
    assert "chmod 755" in content, "Script must set permissions to 755"
