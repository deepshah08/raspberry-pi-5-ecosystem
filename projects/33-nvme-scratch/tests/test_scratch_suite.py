import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from mac_smb_optimizer import MacSMBOptimizer

class TestMacSMBOptimizer:
    def test_generate_nsmb_conf_content(self):
        optimizer = MacSMBOptimizer()
        test_config = {
            "default": {
                "mc_on": "yes",
                "client_signing": "no"
            }
        }
        expected = "[default]\nmc_on=yes\nclient_signing=no\n"
        result = optimizer.generate_nsmb_conf_content(test_config)
        assert result == expected

    @patch("mac_smb_optimizer.Path.write_text")
    @patch("mac_smb_optimizer.Path.mkdir")
    def test_apply_nsmb_tuning(self, mock_mkdir, mock_write_text):
        optimizer = MacSMBOptimizer(nsmb_path="/tmp/test_nsmb.conf")
        optimizer.apply_nsmb_tuning()
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_write_text.assert_called_once()
        content = mock_write_text.call_args[0][0]
        assert "[default]" in content
        assert "mc_on=yes" in content

    @patch("mac_smb_optimizer.subprocess.run")
    def test_disable_ds_store_on_network(self, mock_subprocess):
        optimizer = MacSMBOptimizer()
        optimizer.disable_ds_store_on_network()
        mock_subprocess.assert_called_once_with(
            ["defaults", "write", "com.apple.desktopservices", "DSDontWriteNetworkStores", "-bool", "TRUE"],
            check=True,
            capture_output=True,
            text=True
        )

    @patch("mac_smb_optimizer.subprocess.run")
    def test_configure_tcp_window_scaling(self, mock_subprocess):
        optimizer = MacSMBOptimizer()
        optimizer.configure_tcp_window_scaling()
        mock_subprocess.assert_called_once_with(
            ["sysctl", "-w", "net.inet.tcp.rfc1323=1"],
            check=True,
            capture_output=True,
            text=True
        )

    @patch("mac_smb_optimizer.os.access")
    @patch("mac_smb_optimizer.Path.exists")
    def test_validate_nvme_permissions(self, mock_exists, mock_access):
        optimizer = MacSMBOptimizer()

        # Test path does not exist
        mock_exists.return_value = False
        assert not optimizer.validate_nvme_permissions("/dummy/path")

        # Test path exists, but no permissions
        mock_exists.return_value = True
        mock_access.return_value = False
        assert not optimizer.validate_nvme_permissions("/dummy/path")

        # Test path exists and has permissions
        mock_access.return_value = True
        assert optimizer.validate_nvme_permissions("/dummy/path")

from benchmark_scratch import BenchmarkScratch

class TestBenchmarkScratch:
    @patch("benchmark_scratch.os.urandom")
    def test_measure_sequential_write(self, mock_urandom, tmp_path):
        mock_urandom.return_value = b'x' * (1024 * 1024)
        benchmark = BenchmarkScratch(target_dir=str(tmp_path))
        benchmark.setup()

        # We can't perfectly mock time.time in this simple test without affecting the file operations
        # so we'll just check if it returns a float > 0
        result = benchmark.measure_sequential_write(file_size_mb=1)
        assert isinstance(result, float)
        assert result > 0
        assert (tmp_path / "seq_write.tmp").exists()

    def test_measure_sequential_read(self, tmp_path):
        benchmark = BenchmarkScratch(target_dir=str(tmp_path))
        benchmark.setup()

        # Create a dummy file first
        test_file = tmp_path / "seq_write.tmp"
        test_file.write_bytes(b'x' * (1024 * 1024))

        result = benchmark.measure_sequential_read(file_size_mb=1)
        assert isinstance(result, float)
        assert result > 0

    @patch("benchmark_scratch.os.urandom")
    def test_measure_random_iops_and_latency(self, mock_urandom, tmp_path):
        mock_urandom.return_value = b'y' * 4096
        benchmark = BenchmarkScratch(target_dir=str(tmp_path))
        benchmark.setup()

        result = benchmark.measure_random_iops_and_latency(file_size_mb=1, iterations=10)
        assert "iops" in result
        assert "latency_ms" in result
        assert result["iops"] > 0
        assert result["latency_ms"] >= 0

    def test_generate_json_report(self, tmp_path):
        benchmark = BenchmarkScratch(target_dir=str(tmp_path))
        test_results = {
            "sequential_write_mbps": 280.5,
            "sequential_read_mbps": 285.1,
            "random_4k_iops": 5000.0,
            "average_latency_ms": 1.5
        }
        output_file = tmp_path / "test_report.json"

        benchmark.generate_json_report(test_results, output_path=str(output_file))

        assert output_file.exists()
        with open(output_file, "r") as f:
            data = json.load(f)
            assert data["sequential_write_mbps"] == 280.5

    def test_generate_markdown_report(self, tmp_path):
        benchmark = BenchmarkScratch(target_dir=str(tmp_path))
        test_results = {
            "sequential_write_mbps": 280.5,
            "sequential_read_mbps": 285.1,
            "random_4k_iops": 5000.0,
            "average_latency_ms": 1.5
        }
        output_file = tmp_path / "test_report.md"

        benchmark.generate_markdown_report(test_results, output_path=str(output_file))

        assert output_file.exists()
        with open(output_file, "r") as f:
            content = f.read()
            assert "280.5 MB/s" in content
            assert "5000.0 IOPS" in content
