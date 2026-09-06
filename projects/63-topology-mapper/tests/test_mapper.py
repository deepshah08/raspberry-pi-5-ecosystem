import os
import sys
from pathlib import Path
import pytest
from unittest.mock import patch, mock_open

# Clean up any potential module conflicts
sys.modules.pop('topology_mapper', None)
sys.modules.pop('requests', None)

# Ensure script can be run standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from topology_mapper import (
    get_vendor,
    parse_arp_cache,
    discover_hostnames,
    load_devices,
    save_devices,
    generate_mermaid
)

# Mock data
MOCK_ARP_CONTENT = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.10     0x1         0x2         b8:27:eb:aa:bb:cc     *        eth0
192.168.1.80     0x1         0x2         00:11:32:11:22:33     *        eth0
192.168.1.100    0x1         0x2         ff:ee:dd:cc:bb:aa     *        eth0
"""

@pytest.fixture
def mock_arp_file():
    with patch("builtins.open", mock_open(read_data=MOCK_ARP_CONTENT)) as m:
        yield m

@pytest.fixture
def mock_zeroconf():
    with patch("topology_mapper.ServiceBrowser") as mock_browser, \
         patch("topology_mapper.Zeroconf") as mock_zc, \
         patch("topology_mapper.time.sleep"):

        # We need to mock the behavior where listener gathers hostnames
        def mock_init(*args, **kwargs):
            listener = args[2]
            listener.hostnames = {
                "192.168.1.10": "pi-hole-node",
                "192.168.1.80": "ugreen-nas"
            }
            return mock_browser.return_value

        mock_browser.side_effect = mock_init
        yield mock_zc


def test_get_vendor():
    assert get_vendor("B8:27:EB:11:22:33") == "Raspberry Pi Foundation"
    assert get_vendor("00:11:32:AA:BB:CC") == "Synology Incorporated"
    assert get_vendor("FF:FF:FF:FF:FF:FF") == "Unknown Vendor"

def test_parse_arp_cache(mock_arp_file):
    devices = parse_arp_cache(dry_run=False)
    assert len(devices) == 3
    assert devices[0] == {"ip": "192.168.1.10", "mac": "b8:27:eb:aa:bb:cc"}
    assert devices[1] == {"ip": "192.168.1.80", "mac": "00:11:32:11:22:33"}
    assert devices[2] == {"ip": "192.168.1.100", "mac": "ff:ee:dd:cc:bb:aa"}

def test_parse_arp_cache_dry_run():
    devices = parse_arp_cache(dry_run=True)
    assert len(devices) == 3
    assert devices[0]["mac"] == "B8:27:EB:AA:BB:CC"

def test_discover_hostnames(mock_zeroconf):
    hostnames = discover_hostnames(dry_run=False)
    assert hostnames.get("192.168.1.10") == "pi-hole-node"
    assert hostnames.get("192.168.1.80") == "ugreen-nas"
    assert hostnames.get("192.168.1.100") is None

def test_generate_mermaid():
    registry = {
        "b8:27:eb:aa:bb:cc": {
            "status": "active",
            "hostname": "pi-hole-node",
            "ip": "192.168.1.10",
            "vendor": "Raspberry Pi Foundation"
        },
        "ff:ee:dd:cc:bb:aa": {
            "status": "offline",
            "hostname": "Unknown",
            "ip": "192.168.1.100",
            "vendor": "Unknown Vendor"
        }
    }

    mermaid_str = generate_mermaid(registry)
    assert "graph TD" in mermaid_str
    assert "Router[Gateway/Router]" in mermaid_str
    assert "b827ebaabbcc[\"pi-hole-node<br>192.168.1.10<br>Raspberry Pi Foundation\"]" in mermaid_str
    assert "ffeeddccbbaa" not in mermaid_str # Offline devices are not graphed

@patch('topology_mapper.get_pihole_leases')
@patch('topology_mapper.alert_rogue_device')
@patch('topology_mapper.discover_hostnames')
@patch('topology_mapper.parse_arp_cache')
def test_rogue_device_detection(mock_parse_arp, mock_discover, mock_alert, mock_leases, tmp_path):
    # Setup mock returns
    mock_parse_arp.return_value = [{"ip": "192.168.1.50", "mac": "aa:bb:cc:dd:ee:ff"}]
    mock_discover.return_value = {}
    mock_leases.return_value = {} # Empty leases to simulate rogue device

    # Run main logic via patching sys.argv
    test_args = ["topology_mapper.py", "--scan-now", "--output", str(tmp_path)]
    with patch.object(sys, 'argv', test_args):
        from topology_mapper import main
        main()

    # Verify alert was called for the new device
    mock_alert.assert_called_once_with("aa:bb:cc:dd:ee:ff", "192.168.1.50", "Unknown Vendor", False)

    # Verify devices.json was written
    import os; assert os.path.exists(tmp_path / "devices.json")

    # Run again, alert should NOT be called for existing device
    mock_alert.reset_mock()
    with patch.object(sys, 'argv', test_args):
        main()

    mock_alert.assert_not_called()

    # Reset and test known lease scenario
    mock_alert.reset_mock()
    # Now it is in leases, so it shouldn't alert even if new
    mock_leases.return_value = {"aa:bb:cc:dd:ee:ff": {"ip": "192.168.1.50"}}

    # Remove from devices.json to make it seem new
    import os
    os.remove(tmp_path / "devices.json")

    with patch.object(sys, 'argv', test_args):
        main()

    mock_alert.assert_not_called()