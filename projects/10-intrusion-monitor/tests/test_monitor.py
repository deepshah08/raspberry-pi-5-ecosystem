import pytest
import json
import time
import os
import sys
from unittest.mock import patch, mock_open
from scapy.all import Ether, ARP, IP, TCP

# Add parent directory to path so monitor can be imported cleanly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import monitor

@pytest.fixture(autouse=True)
def reset_state():
    """Reset global state before each test."""
    monitor.arp_table.clear()
    monitor.connection_history.clear()
    if hasattr(monitor.process_packet, "packet_count"):
        delattr(monitor.process_packet, "packet_count")

@patch('monitor.log_event')
def test_arp_spoofing_detection(mock_log_event):
    # Valid ARP reply
    pkt1 = Ether(src="00:11:22:33:44:55", dst="ff:ff:ff:ff:ff:ff") / ARP(op=2, psrc="192.168.1.100", hwsrc="00:11:22:33:44:55")
    monitor.process_packet(pkt1)
    
    mock_log_event.assert_not_called()
    assert monitor.arp_table["192.168.1.100"] == "00:11:22:33:44:55"
    
    # ARP spoofing reply (same IP, different MAC)
    pkt2 = Ether(src="aa:bb:cc:dd:ee:ff", dst="ff:ff:ff:ff:ff:ff") / ARP(op=2, psrc="192.168.1.100", hwsrc="aa:bb:cc:dd:ee:ff")
    monitor.process_packet(pkt2)
    
    mock_log_event.assert_called_once_with("ARP_SPOOFING", {
        "ip": "192.168.1.100",
        "old_mac": "00:11:22:33:44:55",
        "new_mac": "aa:bb:cc:dd:ee:ff"
    })
    # Table should be updated after alert
    assert monitor.arp_table["192.168.1.100"] == "aa:bb:cc:dd:ee:ff"

@patch('monitor.log_event')
def test_port_scan_detection(mock_log_event):
    attacker_ip = "192.168.1.50"
    target_ip = "192.168.1.10"
    
    for port in range(1, monitor.PORT_SCAN_THRESHOLD + 1):
        pkt = IP(src=attacker_ip, dst=target_ip) / TCP(dport=port, flags="S")
        monitor.process_packet(pkt)
        
    assert mock_log_event.call_count == 1
    call_args = mock_log_event.call_args[0]
    assert call_args[0] == "PORT_SCAN"
    assert call_args[1]["source_ip"] == attacker_ip
    assert len(call_args[1]["ports_scanned"]) == monitor.PORT_SCAN_THRESHOLD
    assert call_args[1]["ports_scanned"] == sorted(list(range(1, monitor.PORT_SCAN_THRESHOLD + 1)))

@patch('monitor.log_event')
def test_unexpected_ip_detection(mock_log_event):
    # Unexpected source IP (10.0.0.5 not in 192.168.1.0/24)
    pkt1 = IP(src="10.0.0.5", dst="192.168.1.10") / TCP(dport=80, flags="S")
    monitor.process_packet(pkt1)
    
    mock_log_event.assert_called_with("UNEXPECTED_IP", {
        "ip": "10.0.0.5",
        "direction": "source"
    })
    
    mock_log_event.reset_mock()
    
    # Unexpected destination IP (172.16.0.5 not in 192.168.1.0/24)
    pkt2 = IP(src="192.168.1.10", dst="172.16.0.5") / TCP(dport=80, flags="S")
    monitor.process_packet(pkt2)
    
    mock_log_event.assert_called_with("UNEXPECTED_IP", {
        "ip": "172.16.0.5",
        "direction": "destination"
    })
    
    mock_log_event.reset_mock()
    
    # Allowed subnet IP
    pkt3 = IP(src="192.168.1.10", dst="192.168.1.20") / TCP(dport=80, flags="S")
    monitor.process_packet(pkt3)
    
    mock_log_event.assert_not_called()

def test_json_logging(tmpdir):
    log_file = tmpdir.join("test_intrusion.json")
    original_log_file = monitor.LOG_FILE
    monitor.LOG_FILE = str(log_file)
    
    try:
        monitor.log_event("TEST_EVENT", {"key": "value"})
        
        assert os.path.exists(str(log_file))
        with open(str(log_file), "r") as f:
            lines = f.readlines()
            assert len(lines) == 1
            log_entry = json.loads(lines[0])
            
            assert "timestamp" in log_entry
            assert log_entry["type"] == "TEST_EVENT"
            assert log_entry["details"] == {"key": "value"}
    finally:
        monitor.LOG_FILE = original_log_file

def test_stale_connection_history_cleanup():
    monitor.connection_history["192.168.1.99"].append((time.time() - 100, 80))
    monitor.process_packet.packet_count = 999
    
    pkt = IP(src="192.168.1.10", dst="192.168.1.20") / TCP(dport=80)
    monitor.process_packet(pkt)
    
    assert "192.168.1.99" not in monitor.connection_history
