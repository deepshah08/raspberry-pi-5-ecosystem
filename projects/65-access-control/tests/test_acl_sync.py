import sys
import json
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch, mock_open

# Ensure we can import acl_sync by inserting the parent parent directory (the root of projects or the project folder itself)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acl_sync import parse_peers_file, validate_cidrs, generate_nginx_snippet, main

def test_parse_peers_file(tmp_path):
    peers_file = tmp_path / "peers.json"

    # Test valid JSON with valid data
    data = {
        "peer1": {"ip": "10.0.0.2/32", "other": "data"},
        "peer2": {"ip": "10.0.0.3/32"},
        "peer3": {"other": "data"} # missing ip
    }
    peers_file.write_text(json.dumps(data))

    ips = parse_peers_file(peers_file)
    assert "10.0.0.2/32" in ips
    assert "10.0.0.3/32" in ips
    assert len(ips) == 2

def test_parse_peers_file_not_exist(tmp_path):
    peers_file = tmp_path / "nonexistent.json"
    ips = parse_peers_file(peers_file)
    assert ips == []

def test_parse_peers_file_invalid_json(tmp_path):
    peers_file = tmp_path / "invalid.json"
    peers_file.write_text("{invalid_json: true")
    ips = parse_peers_file(peers_file)
    assert ips == []

def test_validate_cidrs():
    ips = [
        "192.168.1.0/24",
        "10.0.0.2/32",
        "10.0.0.3", # implicit /32 or /128
        "invalid_ip",
        "256.0.0.1"
    ]

    valid_cidrs = validate_cidrs(ips)

    assert "192.168.1.0/24" in valid_cidrs
    assert "10.0.0.2/32" in valid_cidrs
    assert "10.0.0.3/32" in valid_cidrs
    assert len(valid_cidrs) == 3

def test_generate_nginx_snippet():
    cidrs = ["192.168.1.0/24", "10.0.0.2/32"]
    snippet = generate_nginx_snippet(cidrs)

    assert "allow 192.168.1.0/24;" in snippet
    assert "allow 10.0.0.2/32;" in snippet
    assert "deny all;" in snippet
    assert snippet.endswith("\n")
    assert snippet.count("allow") == 2

@patch("sys.argv", ["acl_sync.py", "--peers-file", "dummy.json", "--output", "dummy.conf", "--dry-run"])
@patch("acl_sync.parse_peers_file")
@patch("builtins.print")
def test_main_dry_run(mock_print, mock_parse_peers_file):
    mock_parse_peers_file.return_value = ["10.0.0.2/32"]

    main()

    # Check that print was called with the snippet
    called = False
    for call in mock_print.call_args_list:
        if "allow 192.168.1.0/24;" in call[0][0] and "allow 10.0.0.2/32;" in call[0][0]:
            called = True
    assert called

@patch("sys.argv", ["acl_sync.py", "--peers-file", "dummy.json", "--output", "dummy.conf", "--reload-nginx"])
@patch("acl_sync.parse_peers_file")
@patch("acl_sync.Path.mkdir")
@patch("builtins.open", new_callable=mock_open)
def test_main_write_file(mock_open_file, mock_mkdir, mock_parse_peers_file):
    mock_parse_peers_file.return_value = ["10.0.0.2/32"]

    main()

    mock_open_file.assert_called_once()
    handle = mock_open_file()

    written_data = "".join(call[0][0] for call in handle.write.call_args_list)
    assert "allow 192.168.1.0/24;" in written_data
    assert "allow 10.0.0.2/32;" in written_data
    assert "deny all;" in written_data
