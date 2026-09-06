import json
import logging
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Setup pathing for test execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from thermal_sentry import ThermalSentry, ThermalState


@pytest.fixture
def mock_sys_path(tmp_path):
    sys_dir = tmp_path / "sys"

    # Setup CPU zone
    cpu_path = sys_dir / "class" / "thermal" / "thermal_zone0"
    cpu_path.mkdir(parents=True)
    (cpu_path / "temp").write_text("38000")

    # Setup NVMe zone
    nvme_path = sys_dir / "class" / "hwmon" / "hwmon0"
    nvme_path.mkdir(parents=True)
    (nvme_path / "temp1_input").write_text("42000")

    # Setup HDD zone
    hdd_path = sys_dir / "class" / "hwmon" / "hwmon1"
    hdd_path.mkdir(parents=True)
    (hdd_path / "temp1_input").write_text("35000")

    return sys_dir

def test_thermal_reader(mock_sys_path):
    sentry = ThermalSentry(sys_path=str(mock_sys_path))
    assert sentry.read_cpu_temp() == 38.0
    assert sentry.read_nvme_temp() == 42.0
    assert sentry.read_hdd_temp() == 35.0

def test_thermal_zones():
    assert ThermalState.from_temp(39.9) == ThermalState.COOL
    assert ThermalState.from_temp(40.0) == ThermalState.OPTIMAL
    assert ThermalState.from_temp(54.9) == ThermalState.OPTIMAL
    assert ThermalState.from_temp(55.0) == ThermalState.WARM
    assert ThermalState.from_temp(64.9) == ThermalState.WARM
    assert ThermalState.from_temp(65.0) == ThermalState.CRITICAL
    assert ThermalState.from_temp(85.0) == ThermalState.CRITICAL

def test_rate_of_rise(mock_sys_path):
    sentry = ThermalSentry(sys_path=str(mock_sys_path))

    current_time = time.time()

    # Initial read
    rate1 = sentry.update_history_and_check_rate("cpu", 40.0, current_time)
    assert rate1 == 0.0

    # 30 seconds later, temp goes to 43.0.
    # Change is +3.0 in 0.5 minutes = +6.0 C / min
    rate2 = sentry.update_history_and_check_rate("cpu", 43.0, current_time + 30)
    assert rate2 == 6.0

def test_alerts_triggered_on_thresholds(mock_sys_path):
    sentry = ThermalSentry(sys_path=str(mock_sys_path))
    sentry.alert_router.dispatch = MagicMock()

    # Manually trigger the alert check with a high temperature state
    sentry._check_alerts(cpu=40.0, nvme=42.0, hdd=66.0, max_temp=66.0, state=ThermalState.CRITICAL, rates={"cpu": 0, "nvme": 0, "hdd": 0})

    # Verify alert was dispatched
    sentry.alert_router.dispatch.assert_called_once()
    args, kwargs = sentry.alert_router.dispatch.call_args
    assert args[1] == "Thermal State CRITICAL"
    assert "66.0" in args[2]

def test_alerts_triggered_on_rate_of_rise(mock_sys_path):
    sentry = ThermalSentry(sys_path=str(mock_sys_path))
    sentry.alert_router.dispatch = MagicMock()

    # Trigger alert for high rate of rise (6.0 C/min) on CPU
    sentry._check_alerts(cpu=40.0, nvme=40.0, hdd=40.0, max_temp=40.0, state=ThermalState.OPTIMAL, rates={"cpu": 6.0, "nvme": 0, "hdd": 0})

    sentry.alert_router.dispatch.assert_called_once()
    args, kwargs = sentry.alert_router.dispatch.call_args
    assert "Rapid Temp Rise: CPU" in args[1]
    assert "6.0°C/min" in args[2]

@patch("thermal_sentry.time.time")
def test_full_cycle_output(mock_time, mock_sys_path):
    mock_time.return_value = 1000.0
    sentry = ThermalSentry(sys_path=str(mock_sys_path), dry_run=True)

    data = sentry.run_cycle()

    assert data["cpu_temp"] == 38.0
    assert data["nvme_temp"] == 42.0
    assert data["hdd_temp"] == 35.0
    assert data["max_temp"] == 42.0
    assert data["state"] == "OPTIMAL"
