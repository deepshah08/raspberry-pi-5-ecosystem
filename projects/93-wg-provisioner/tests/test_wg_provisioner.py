import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest
from unittest.mock import patch, MagicMock
from wg_provisioner import WireGuardProvisioner

@pytest.fixture
def temp_config_dir(tmp_path):
    return tmp_path / "wg_test"

@pytest.fixture
def provisioner(temp_config_dir):
    return WireGuardProvisioner(str(temp_config_dir))

def test_generate_keypair():
    priv, pub = WireGuardProvisioner.generate_keypair()
    assert isinstance(priv, str)
    assert isinstance(pub, str)
    assert len(priv) > 20
    assert len(pub) > 20

def test_generate_preshared_key():
    psk = WireGuardProvisioner.generate_preshared_key()
    assert isinstance(psk, str)
    assert len(psk) > 20

def test_allocate_ip(provisioner):
    # Should start with .2
    ip1 = provisioner.allocate_ip()
    assert ip1 == "10.13.13.2"

    # Mock state
    provisioner.peers = {
        "client1": {"ip": "10.13.13.2"},
        "client2": {"ip": "10.13.13.3"}
    }

    ip2 = provisioner.allocate_ip()
    assert ip2 == "10.13.13.4"

def test_allocate_ip_exhaustion(provisioner):
    # Fill up subnet
    provisioner.peers = {f"client{i}": {"ip": f"10.13.13.{i}"} for i in range(2, 255)}

    with pytest.raises(ValueError, match="No available IP addresses"):
        provisioner.allocate_ip()

def test_generate_client_config(provisioner):
    config = provisioner.generate_client_config("test", "privkey", "psk", "10.13.13.5")
    assert "[Interface]" in config
    assert "PrivateKey = privkey" in config
    assert "Address = 10.13.13.5/32" in config
    assert "[Peer]" in config
    assert "PresharedKey = psk" in config

@patch("wg_provisioner.qrcode.QRCode")
def test_generate_qr_code(mock_qr, provisioner, temp_config_dir):
    mock_instance = mock_qr.return_value
    provisioner.generate_qr_code("config_content", "test_peer", temp_config_dir)

    mock_instance.add_data.assert_called_with("config_content")
    mock_instance.make.assert_called_with(fit=True)
    mock_instance.print_ascii.assert_called_with(invert=True)
    mock_instance.make_image.assert_called()

@patch('sys.exit')
def test_create_peer(mock_exit, provisioner, temp_config_dir):
    # Test normal creation
    provisioner.create_peer("new_peer")

    assert "new_peer" in provisioner.peers
    assert provisioner.peers["new_peer"]["ip"] == "10.13.13.2"
    assert provisioner.peers["new_peer"]["status"] == "active"

    conf_path = temp_config_dir / "new_peer.conf"
    png_path = temp_config_dir / "new_peer.png"
    assert conf_path.exists()
    assert png_path.exists()

    # Test duplicate creation
    provisioner.create_peer("new_peer")
    mock_exit.assert_called_with(1)

def test_remove_peer(provisioner, temp_config_dir):
    # Setup
    provisioner.create_peer("to_remove")
    assert "to_remove" in provisioner.peers
    conf_path = temp_config_dir / "to_remove.conf"
    png_path = temp_config_dir / "to_remove.png"
    assert conf_path.exists()
    assert png_path.exists()

    # Remove
    provisioner.remove_peer("to_remove")

    assert "to_remove" not in provisioner.peers
    assert not conf_path.exists()
    assert not png_path.exists()

@patch('sys.exit')
def test_remove_nonexistent_peer(mock_exit, provisioner):
    provisioner.remove_peer("does_not_exist")
    mock_exit.assert_called_with(1)

def test_dry_run_create(provisioner, temp_config_dir):
    provisioner.create_peer("dry_peer", dry_run=True)

    assert "dry_peer" not in provisioner.peers
    assert not (temp_config_dir / "dry_peer.conf").exists()

@patch('wg_provisioner.WireGuardProvisioner.generate_keypair')
def test_create_peer_mocked_keys(mock_gen_keys, provisioner, temp_config_dir):
    mock_gen_keys.return_value = ("mock_priv", "mock_pub")
    provisioner.create_peer("mocked_peer")
    assert "mocked_peer" in provisioner.peers
    assert provisioner.peers["mocked_peer"]["public_key"] == "mock_pub"
    assert "preshared_key" not in provisioner.peers["mocked_peer"]

@patch('sys.argv', ['wg_provisioner.py', '--create-peer', 'cli_peer', '--config-dir', 'test_cli_dir'])
@patch('wg_provisioner.WireGuardProvisioner.create_peer')
@patch('wg_provisioner.Path.mkdir')
def test_cli_create_peer(mock_mkdir, mock_create):
    from wg_provisioner import main
    main()
    mock_create.assert_called_with('cli_peer', dry_run=False, json_output=False)

@patch('sys.argv', ['wg_provisioner.py', '--list-peers', '--config-dir', 'test_cli_dir'])
@patch('wg_provisioner.WireGuardProvisioner.list_peers')
@patch('wg_provisioner.Path.mkdir')
def test_cli_list_peers(mock_mkdir, mock_list):
    from wg_provisioner import main
    main()
    mock_list.assert_called_with(json_output=False)
