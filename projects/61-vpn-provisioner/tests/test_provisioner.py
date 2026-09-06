import sys
import os
import json
import base64
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from provisioner import Provisioner

@pytest.fixture
def temp_config_dir(tmp_path):
    return str(tmp_path / "clients")

@pytest.fixture
def provisioner(temp_config_dir):
    return Provisioner(config_dir=temp_config_dir)

def test_keypair_generation(provisioner):
    priv, pub = provisioner.generate_keypair()
    assert isinstance(priv, str)
    assert isinstance(pub, str)
    # Check if base64 decodable
    assert len(base64.b64decode(priv)) == 32
    assert len(base64.b64decode(pub)) == 32

    psk = provisioner.generate_psk()
    assert isinstance(psk, str)
    assert len(base64.b64decode(psk)) == 32

def test_peer_creation_and_duplicate(provisioner, temp_config_dir):
    peer_data = provisioner.add_peer("test-peer")
    assert peer_data["name"] == "test-peer"
    assert peer_data["ip"] == "10.66.66.2"
    assert "public_key" in peer_data
    assert "psk" in peer_data

    # Verify files created
    config_file = Path(temp_config_dir) / "test-peer.conf"
    assert config_file.exists()

    # Test Duplicate
    with pytest.raises(ValueError, match="already exists"):
        provisioner.add_peer("test-peer")

def test_ip_pool_exhaustion(provisioner):
    # Simulate allocating almost all IPs
    for i in range(2, 255):
        provisioner.peers[f"peer-{i}"] = {"ip": f"10.66.66.{i}"}

    with pytest.raises(RuntimeError, match="IP pool exhausted"):
        provisioner.allocate_ip()

def test_qr_generation(provisioner, temp_config_dir):
    provisioner.add_peer("qr-peer")

    # PNG generation
    provisioner.generate_qr("qr-peer")
    png_file = Path(temp_config_dir) / "qr-peer.png"
    assert png_file.exists()

    # Terminal QR generation
    ascii_qr = provisioner.generate_qr("qr-peer", terminal=True)
    assert isinstance(ascii_qr, str)
    assert len(ascii_qr) > 0

def test_revocation(provisioner, temp_config_dir):
    provisioner.add_peer("revoke-peer")
    provisioner.generate_qr("revoke-peer")

    config_file = Path(temp_config_dir) / "revoke-peer.conf"
    png_file = Path(temp_config_dir) / "revoke-peer.png"

    assert config_file.exists()
    assert png_file.exists()

    provisioner.revoke_peer("revoke-peer")

    assert "revoke-peer" not in provisioner.peers
    assert not config_file.exists()
    assert not png_file.exists()

    with pytest.raises(ValueError, match="not found"):
        provisioner.revoke_peer("nonexistent")

def test_cli_commands(temp_config_dir, monkeypatch, capsys):
    from provisioner import main

    # Test ADD
    monkeypatch.setattr("sys.argv", ["vpnctl", "--config-dir", temp_config_dir, "--json", "add", "cli-peer"])
    main()
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["name"] == "cli-peer"
    assert output["ip"] == "10.66.66.2"

    # Test LIST
    monkeypatch.setattr("sys.argv", ["vpnctl", "--config-dir", temp_config_dir, "--json", "list"])
    main()
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert "cli-peer" in output

    # Test QR
    monkeypatch.setattr("sys.argv", ["vpnctl", "--config-dir", temp_config_dir, "--json", "qr", "cli-peer"])
    main()
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["status"] == "qr_generated"

    # Test REVOKE
    monkeypatch.setattr("sys.argv", ["vpnctl", "--config-dir", temp_config_dir, "--json", "revoke", "cli-peer"])
    main()
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["status"] == "revoked"
