import pytest
import json
from unittest.mock import patch, MagicMock
from io import StringIO
import sys

# Update path to allow importing labctl
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import labctl

class TestLabctl:

    @patch('labctl.requests.get')
    def test_status_command_success(self, mock_get):
        # Mocking Node Exporter and Uptime Kuma responses
        mock_node_resp = MagicMock()
        mock_node_resp.text = (
            "node_memory_MemTotal_bytes 1000000\n"
            "node_memory_MemAvailable_bytes 800000\n"
            "node_hwmon_temp_celsius{sensor=\"cpu\"} 45.0\n"
        )
        mock_node_resp.raise_for_status.return_value = None

        mock_kuma_resp = MagicMock()
        mock_kuma_resp.status_code = 200

        # Side effect function to handle different URLs
        def get_side_effect(*args, **kwargs):
            if "3001" in args[0]:
                return mock_kuma_resp
            return mock_node_resp

        mock_get.side_effect = get_side_effect

        # Capture stdout
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            # Simulate CLI arg parsing directly by creating an argparse.Namespace
            args = MagicMock(json=False, command="status")
            labctl.cmd_status(args)
            output = mock_stdout.getvalue()

        assert "NAS" in output
        assert "45.0°C" in output
        assert "20.0%" in output  # (1000000 - 800000) / 1000000 = 20%
        assert "Uptime Kuma" in output
        assert "UP" in output

    @patch('labctl.requests.get')
    def test_status_command_json(self, mock_get):
        mock_node_resp = MagicMock()
        mock_node_resp.text = "node_memory_MemTotal_bytes 1000000\nnode_memory_MemAvailable_bytes 500000\nnode_hwmon_temp_celsius{sensor=\"cpu\"} 50.0\n"
        mock_node_resp.raise_for_status.return_value = None
        mock_kuma_resp = MagicMock()
        mock_kuma_resp.status_code = 200

        def get_side_effect(*args, **kwargs):
            if "3001" in args[0]:
                return mock_kuma_resp
            return mock_node_resp

        mock_get.side_effect = get_side_effect

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=True, command="status")
            labctl.cmd_status(args)
            output = mock_stdout.getvalue()

        json_out = json.loads(output)
        assert json_out["nodes"]["NAS"]["status"] == "UP"
        assert json_out["nodes"]["NAS"]["cpu_temp"] == "50.0°C"
        assert json_out["nodes"]["NAS"]["ram_usage"] == "50.0%"
        assert json_out["services"]["Uptime Kuma"] == "UP"

    @patch('labctl.requests.get')
    def test_search_command_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"score": 0.95, "path": "/media/mountains.jpg"},
                {"score": 0.82, "path": "/media/hike.jpg"}
            ]
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=False, command="search", query="mountains")
            labctl.cmd_search(args)
            output = mock_stdout.getvalue()

        assert "0.9500" in output
        assert "/media/mountains.jpg" in output
        assert "0.8200" in output
        assert "/media/hike.jpg" in output

    @patch('labctl.requests.get')
    def test_search_command_json(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"score": 0.95, "path": "/media/mountains.jpg"}
            ]
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=True, command="search", query="mountains")
            labctl.cmd_search(args)
            output = mock_stdout.getvalue()

        json_out = json.loads(output)
        assert json_out["query"] == "mountains"
        assert len(json_out["matches"]) == 1
        assert json_out["matches"][0]["score"] == 0.95
        assert json_out["matches"][0]["path"] == "/media/mountains.jpg"

    @patch('labctl.requests.get')
    def test_search_command_error(self, mock_get):
        mock_get.side_effect = labctl.requests.exceptions.RequestException("Connection error")

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=True, command="search", query="test")
            labctl.cmd_search(args)
            output = mock_stdout.getvalue()

        json_out = json.loads(output)
        assert json_out["error"] == "Connection error"

    @patch('labctl.requests.get')
    def test_smart_command_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = (
            "smartmon_nvme_percentage_used{disk=\"/dev/nvme0n1\"} 2\n"
            "smartmon_device_state{disk=\"/dev/sdb\",state=\"standby\"} 1\n"
        )
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=False, command="smart")
            labctl.cmd_smart(args)
            output = mock_stdout.getvalue()

        assert "/dev/nvme0n1" in output
        assert "2.0%" in output
        assert "/dev/sdb" in output
        assert "STANDBY" in output

    @patch('labctl.requests.get')
    def test_smart_command_json(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = (
            "smartmon_nvme_percentage_used{disk=\"/dev/nvme0n1\"} 5\n"
            "smartmon_device_state{disk=\"/dev/sda\",state=\"active\"} 1\n"
        )
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=True, command="smart")
            labctl.cmd_smart(args)
            output = mock_stdout.getvalue()

        json_out = json.loads(output)
        assert len(json_out["nvme_wear"]) == 1
        assert json_out["nvme_wear"][0]["disk"] == "/dev/nvme0n1"
        assert json_out["nvme_wear"][0]["wear"] == "5.0%"
        assert len(json_out["hdd_standby"]) == 1
        assert json_out["hdd_standby"][0]["disk"] == "/dev/sda"
        assert json_out["hdd_standby"][0]["state"] == "ACTIVE"

    @patch('labctl.requests.get')
    def test_briefing_command_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"latest_briefing": "Briefing_2024-11-01.mp3"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=False, command="briefing", play=False)
            labctl.cmd_briefing(args)
            output = mock_stdout.getvalue()

        assert "Briefing_2024-11-01.mp3" in output
        assert "Playing" not in output

    @patch('labctl.requests.get')
    def test_briefing_command_play(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"latest_briefing": "Briefing_2024-11-01.mp3"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=False, command="briefing", play=True)
            labctl.cmd_briefing(args)
            output = mock_stdout.getvalue()

        assert "Playing Briefing_2024-11-01.mp3..." in output

    @patch('labctl.socket.gethostbyname')
    @patch('labctl.requests.get')
    @patch('labctl.time.time')
    def test_canary_command_success(self, mock_time, mock_get, mock_gethostbyname):
        # Time mock to control latency calculation.
        # It needs to return pairs of times: [start_dns, end_dns, start_http, end_http]
        # 10ms for DNS, 100ms for HTTP
        mock_time.side_effect = [100.0, 100.010, 100.010, 100.110]

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=False, command="canary")
            labctl.cmd_canary(args)
            output = mock_stdout.getvalue()

        assert "10.0 ms" in output
        assert "100.0 ms" in output
        assert "PASSED" in output

    @patch('labctl.socket.gethostbyname')
    @patch('labctl.requests.get')
    @patch('labctl.time.time')
    def test_canary_command_slo_breach(self, mock_time, mock_get, mock_gethostbyname):
        # 60ms for DNS, triggering breach
        mock_time.side_effect = [100.0, 100.060, 100.060, 100.160]

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=False, command="canary")
            labctl.cmd_canary(args)
            output = mock_stdout.getvalue()

        assert "60.0 ms" in output
        assert "FAILED (SLO Breach)" in output

    @patch('labctl.subprocess.run')
    def test_backup_command_success(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Backup completed."
        mock_run.return_value = mock_result

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=False, command="backup", dry_run=False)
            labctl.cmd_backup(args)
            output = mock_stdout.getvalue()

        assert "Triggering backup" in output
        assert "Backup completed." in output
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        assert "--dry-run" not in called_cmd

    @patch('labctl.subprocess.run')
    def test_backup_command_dry_run_json(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Dry run backup."
        mock_run.return_value = mock_result

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=True, command="backup", dry_run=True)
            labctl.cmd_backup(args)
            output = mock_stdout.getvalue()

        json_out = json.loads(output)
        assert json_out["status"] == "success"
        assert json_out["dry_run"] is True
        assert json_out["output"] == "Dry run backup."
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        assert "--dry-run" in called_cmd

    @patch('labctl.subprocess.run')
    def test_backup_command_error(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, ["python3", "script.py"], stderr="Rsync error")

        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            args = MagicMock(json=True, command="backup", dry_run=False)
            labctl.cmd_backup(args)
            output = mock_stdout.getvalue()

        json_out = json.loads(output)
        assert json_out["status"] == "failed"
        assert json_out["error"] == "Rsync error"
