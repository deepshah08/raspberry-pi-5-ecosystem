import json
import pytest
from unittest.mock import patch, MagicMock
from prometheus_client import REGISTRY

# We need to import our script. We'll load it dynamically or adjust PYTHONPATH.
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import smart_sentinel

@pytest.fixture(autouse=True)
def reset_metrics():
    # Clear metrics before each test to prevent pollution
    # This is slightly hacky but works for prometheus_client Gauges
    for metric in [smart_sentinel.SMART_NVME_PERCENTAGE_USED,
                   smart_sentinel.SMART_NVME_AVAILABLE_SPARE,
                   smart_sentinel.SMART_NVME_TBW_WRITTEN_TERABYTES,
                   smart_sentinel.SMART_NVME_LIFESPAN_REMAINING_PERCENT,
                   smart_sentinel.SMART_HDD_REALLOCATED_SECTORS,
                   smart_sentinel.SMART_HDD_SPIN_RETRY_COUNT,
                   smart_sentinel.SMART_DRIVE_TEMPERATURE_CELSIUS,
                   smart_sentinel.SMART_DISK_STANDBY_STATE]:
        metric._metrics.clear()

    # Also mock telegram
    with patch('smart_sentinel.send_telegram_alert') as mock_alert:
        yield mock_alert

def get_metric_value(metric, labels):
    try:
        if tuple(labels.values()) in metric._metrics:
            return metric.labels(**labels)._value.get()
        return None
    except KeyError:
        return None

def test_nvme_parsing(reset_metrics):
    device = "/dev/nvme0n1"
    info = {'type': 'nvme', 'name': 'Test NVMe'}

    # Mock NVMe JSON
    mock_json = json.dumps({
        "smartctl": {"messages": [{"string": "smartctl 7.2"}]},
        "device": {"name": "/dev/nvme0n1", "info_name": "WD_BLACK SN850X", "type": "nvme"},
        "power_cycle_info": {"power_mode": "active"},
        "nvme_smart_health_information_log": {
            "critical_warning": 0,
            "temperature": 45,
            "available_spare": 99,
            "available_spare_threshold": 10,
            "percentage_used": 2,
            "data_units_read": 1000,
            "data_units_written": 2000000000,
            "host_reads": 1000,
            "host_writes": 2000,
            "controller_busy_time": 10,
            "power_cycles": 100,
            "power_on_hours": 1000,
            "unsafe_shutdowns": 5,
            "media_errors": 0,
            "num_err_log_entries": 0
        }
    })

    smart_sentinel.parse_smart_data(device, mock_json, info)

    assert get_metric_value(smart_sentinel.SMART_DISK_STANDBY_STATE, {'device': device}) == 1.0
    assert get_metric_value(smart_sentinel.SMART_NVME_PERCENTAGE_USED, {'device': device}) == 2.0
    assert get_metric_value(smart_sentinel.SMART_NVME_AVAILABLE_SPARE, {'device': device}) == 99.0
    assert get_metric_value(smart_sentinel.SMART_DRIVE_TEMPERATURE_CELSIUS, {'device': device}) == 45.0

    # TBW Math: 2,000,000,000 units * 512,000 bytes / 10**12 = 1024.0 TB
    assert get_metric_value(smart_sentinel.SMART_NVME_TBW_WRITTEN_TERABYTES, {'device': device}) == 1024.0

    # Lifespan: (2400 - 1024) / 2400 * 100 = 57.333333333333336
    lifespan_pct = get_metric_value(smart_sentinel.SMART_NVME_LIFESPAN_REMAINING_PERCENT, {'device': device})
    assert abs(lifespan_pct - 57.333333333333336) < 0.001

    reset_metrics.assert_not_called() # No alerts

def test_nvme_high_temp_alert(reset_metrics):
    device = "/dev/nvme0n1"
    info = {'type': 'nvme', 'name': 'Test NVMe'}

    mock_json = json.dumps({
        "smartctl": {"messages": [{"string": "smartctl 7.2"}]},
        "power_cycle_info": {"power_mode": "active"},
        "nvme_smart_health_information_log": {
            "critical_warning": 0,
            "temperature": 75,
            "available_spare": 99,
            "percentage_used": 2,
            "data_units_written": 2000000,
        }
    })

    smart_sentinel.parse_smart_data(device, mock_json, info)
    reset_metrics.assert_called_with("High Temperature on Test NVMe (/dev/nvme0n1): 75°C")

def test_hdd_parsing(reset_metrics):
    device = "/dev/sda"
    info = {'type': 'hdd', 'name': 'Test HDD'}

    mock_json = json.dumps({
        "smartctl": {"messages": [{"string": "smartctl 7.2"}]},
        "power_cycle_info": {"power_mode": "active"},
        "temperature": {"current": 38},
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": 0}},
                {"id": 10, "name": "Spin_Retry_Count", "raw": {"value": 0}},
                {"id": 194, "name": "Temperature_Celsius", "raw": {"value": 38}}
            ]
        }
    })

    smart_sentinel.parse_smart_data(device, mock_json, info)

    assert get_metric_value(smart_sentinel.SMART_DISK_STANDBY_STATE, {'device': device}) == 1.0
    assert get_metric_value(smart_sentinel.SMART_DRIVE_TEMPERATURE_CELSIUS, {'device': device}) == 38.0
    assert get_metric_value(smart_sentinel.SMART_HDD_REALLOCATED_SECTORS, {'device': device}) == 0.0
    assert get_metric_value(smart_sentinel.SMART_HDD_SPIN_RETRY_COUNT, {'device': device}) == 0.0
    reset_metrics.assert_not_called()

def test_hdd_critical_alert(reset_metrics):
    device = "/dev/sda"
    info = {'type': 'hdd', 'name': 'Test HDD'}

    mock_json = json.dumps({
        "smartctl": {"messages": [{"string": "smartctl 7.2"}]},
        "power_cycle_info": {"power_mode": "active"},
        "temperature": {"current": 40},
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": 5}},
                {"id": 10, "name": "Spin_Retry_Count", "raw": {"value": 0}},
            ]
        }
    })

    smart_sentinel.parse_smart_data(device, mock_json, info)
    reset_metrics.assert_called_with("Reallocated Sectors on Test HDD (/dev/sda): 5")

def test_standby_state(reset_metrics):
    device = "/dev/sdb"
    info = {'type': 'usb', 'name': 'Test USB HDD'}

    # When smartctl runs with -n standby on a sleeping drive, it outputs messages
    mock_json = json.dumps({
        "smartctl": {
            "messages": [
                {"string": "smartctl 7.2 2020-12-30 r5155 [x86_64-linux-5.15.0-60-generic] (local build)"},
                {"string": "Device is in STANDBY mode, exit(2)"}
            ],
            "exit_status": 2
        },
        "power_mode": "standby"
    })

    # Remove gauge entirely to test its unset state
    smart_sentinel.SMART_DRIVE_TEMPERATURE_CELSIUS._metrics.clear()

    smart_sentinel.parse_smart_data(device, mock_json, info)

    # Metrics should indicate standby (0)
    assert get_metric_value(smart_sentinel.SMART_DISK_STANDBY_STATE, {'device': device}) == 0.0

    # Other metrics should not be set (or should remain none)
    # They should not be instantiated for this device at all
    assert get_metric_value(smart_sentinel.SMART_DRIVE_TEMPERATURE_CELSIUS, {'device': device}) is None

def test_standby_state_via_power_mode(reset_metrics):
    device = "/dev/sdb"
    info = {'type': 'usb', 'name': 'Test USB HDD'}

    # Alternative mock json for sleep
    mock_json = json.dumps({
        "smartctl": {"messages": []},
        "power_mode": "sleep"
    })

    smart_sentinel.parse_smart_data(device, mock_json, info)
    assert get_metric_value(smart_sentinel.SMART_DISK_STANDBY_STATE, {'device': device}) == 0.0
