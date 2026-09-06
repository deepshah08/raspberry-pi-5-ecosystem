import sys
import os
from pathlib import Path
import json
import pytest
from unittest.mock import patch, MagicMock

# Ensure standalone test execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wol_sentry import create_magic_packet, TargetRegistry, verify_liveness, send_magic_packet, main

def test_create_magic_packet_valid():
    mac = "AA:BB:CC:DD:EE:FF"
    packet = create_magic_packet(mac)
    assert len(packet) == 102
    assert packet[:6] == b'\xff' * 6
    expected_mac_bytes = bytes.fromhex("AABBCCDDEEFF")
    assert packet[6:] == expected_mac_bytes * 16

def test_create_magic_packet_invalid():
    with pytest.raises(ValueError):
        create_magic_packet("invalid-mac")
        
def test_create_magic_packet_different_formats():
    mac1 = "AA:BB:CC:DD:EE:FF"
    mac2 = "AA-BB-CC-DD-EE-FF"
    mac3 = "AABBCCDDEEFF"
    
    packet1 = create_magic_packet(mac1)
    packet2 = create_magic_packet(mac2)
    packet3 = create_magic_packet(mac3)
    
    assert packet1 == packet2 == packet3

def test_target_resolution(tmp_path):
    registry_file = tmp_path / "targets.json"
    data = {
        "workstation1": {
            "mac": "11:22:33:44:55:66",
            "ip": "192.168.1.100",
            "last_status": "offline"
        }
    }
    registry_file.write_text(json.dumps(data))
    
    registry = TargetRegistry(registry_file=str(registry_file))
    
    # Test resolving by name
    target = registry.get_target("workstation1")
    assert target.get('mac') == "11:22:33:44:55:66"
    
    # Test resolving by MAC
    target = registry.get_target("11:22:33:44:55:66")
    assert target.get('ip') == "192.168.1.100"
    
    # Test non-existent target
    target = registry.get_target("unknown")
    assert target == {}

def test_update_status(tmp_path):
    registry_file = tmp_path / "targets.json"
    data = {
        "workstation1": {
            "mac": "11:22:33:44:55:66",
            "ip": "192.168.1.100",
            "last_status": "offline"
        }
    }
    registry_file.write_text(json.dumps(data))
    
    registry = TargetRegistry(registry_file=str(registry_file))
    registry.update_status("workstation1", "online")
    
    # Verify status in memory
    assert registry.targets["workstation1"]["last_status"] == "online"
    
    # Verify status on disk
    saved_data = json.loads(registry_file.read_text())
    assert saved_data["workstation1"]["last_status"] == "online"

@patch('subprocess.run')
def test_verify_liveness_success(mock_run):
    mock_run.return_value.returncode = 0
    assert verify_liveness("192.168.1.100") is True

@patch('subprocess.run')
def test_verify_liveness_failure(mock_run):
    mock_run.return_value.returncode = 1
    assert verify_liveness("192.168.1.100") is False

@patch('subprocess.run')
def test_verify_liveness_exception(mock_run):
    mock_run.side_effect = Exception("error")
    assert verify_liveness("192.168.1.100") is False

@patch('socket.socket')
def test_send_magic_packet(mock_socket):
    mock_sock = MagicMock()
    mock_socket.return_value.__enter__.return_value = mock_sock
    
    mac = "AA:BB:CC:DD:EE:FF"
    send_magic_packet(mac)
    
    mock_sock.setsockopt.assert_called_once()
    mock_sock.sendto.assert_called_once()

@patch('wol_sentry.send_magic_packet')
@patch('sys.argv', ['wol_sentry.py', '--wake', 'AA:BB:CC:DD:EE:FF', '--dry-run'])
def test_main_dry_run(mock_send, capsys):
    main()
    mock_send.assert_not_called()
    captured = capsys.readouterr()
    assert "Dry run mode: Packet not sent." in captured.out

@patch('wol_sentry.send_magic_packet')
@patch('wol_sentry.verify_liveness')
@patch('sys.argv', ['wol_sentry.py', '--wake', 'workstation1'])
def test_main_wake(mock_verify, mock_send, tmp_path):
    registry_file = tmp_path / "targets.json"
    data = {
        "workstation1": {
            "mac": "11:22:33:44:55:66",
            "ip": "192.168.1.100",
            "last_status": "offline"
        }
    }
    registry_file.write_text(json.dumps(data))
    
    with patch('wol_sentry.TargetRegistry._load_registry', return_value=data):
        with patch('wol_sentry.TargetRegistry.save_registry'):
            # Set ping to fail first time, then succeed
            mock_verify.side_effect = [False, True]
            main()
            
            mock_send.assert_called_once_with("11:22:33:44:55:66", "255.255.255.255")
            assert mock_verify.call_count == 2
