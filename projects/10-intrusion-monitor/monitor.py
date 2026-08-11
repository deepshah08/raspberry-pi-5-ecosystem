import json
import logging
from collections import defaultdict
import time
import os
import ipaddress
from scapy.all import sniff, ARP, IP, TCP, Ether

# Configuration
LOG_FILE = os.getenv("INTRUSION_LOG_FILE", "/mnt/nas/system_logs/intrusion.json")
ALLOWED_SUBNET = os.getenv("ALLOWED_SUBNET", "192.168.1.0/24")
PORT_SCAN_THRESHOLD = int(os.getenv("PORT_SCAN_THRESHOLD", "20"))
PORT_SCAN_WINDOW = float(os.getenv("PORT_SCAN_WINDOW", "10.0"))

# State
arp_table = {}
connection_history = defaultdict(list)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_event(event_type, details):
    event = {
        "timestamp": time.time(),
        "type": event_type,
        "details": details
    }
    logger.info(f"Intrusion event: {event}")
    try:
        log_dir = os.path.dirname(LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            json.dump(event, f)
            f.write("\n")
    except Exception as e:
        logger.error(f"Failed to log event to {LOG_FILE}: {e}")

def detect_arp_spoofing(packet):
    if packet.haslayer(ARP) and packet[ARP].op in (1, 2):  # ARP Request or Reply
        src_ip = packet[ARP].psrc
        src_mac = packet[ARP].hwsrc
        
        if src_ip in arp_table:
            if arp_table[src_ip] != src_mac:
                log_event("ARP_SPOOFING", {
                    "ip": src_ip,
                    "old_mac": arp_table[src_ip],
                    "new_mac": src_mac
                })
                # Update table so subsequent packets don't flood duplicate alerts
                arp_table[src_ip] = src_mac
        else:
            arp_table[src_ip] = src_mac

def detect_port_scan(packet):
    if packet.haslayer(IP) and packet.haslayer(TCP):
        src_ip = packet[IP].src
        dst_port = packet[TCP].dport
        
        # Check for SYN flag across Scapy versions / flag representations
        flags = packet[TCP].flags
        is_syn = getattr(flags, 'S', False) or (isinstance(flags, str) and 'S' in flags) or (hasattr(flags, 'value') and flags & 0x02) or (flags == "S")
        
        if is_syn:
            now = time.time()
            
            # Add to history
            connection_history[src_ip].append((now, dst_port))
            
            # Clean up old history for this IP
            connection_history[src_ip] = [
                (t, p) for t, p in connection_history[src_ip] 
                if now - t <= PORT_SCAN_WINDOW
            ]
            
            # Check for scan
            unique_ports = set(p for t, p in connection_history[src_ip])
            if len(unique_ports) >= PORT_SCAN_THRESHOLD:
                log_event("PORT_SCAN", {
                    "source_ip": src_ip,
                    "ports_scanned": sorted(list(unique_ports))
                })
                # Clear history so we don't spam logs for this IP immediately
                connection_history[src_ip] = []

def is_private_ip(ip_str):
    try:
        return ipaddress.ip_address(ip_str).is_private
    except ValueError:
        return False

def in_allowed_subnet(ip_str, subnet_str=ALLOWED_SUBNET):
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        net_obj = ipaddress.ip_network(subnet_str, strict=False)
        return ip_obj in net_obj
    except ValueError:
        return False

def detect_unexpected_ip(packet):
    if packet.haslayer(IP):
        src_ip = packet[IP].src
        dst_ip = packet[IP].dst
        
        if is_private_ip(src_ip) and not in_allowed_subnet(src_ip):
            log_event("UNEXPECTED_IP", {
                "ip": src_ip,
                "direction": "source"
            })
            
        if is_private_ip(dst_ip) and not in_allowed_subnet(dst_ip):
            log_event("UNEXPECTED_IP", {
                "ip": dst_ip,
                "direction": "destination"
            })

def process_packet(packet):
    detect_arp_spoofing(packet)
    detect_port_scan(packet)
    detect_unexpected_ip(packet)
    
    if hasattr(process_packet, "packet_count"):
        process_packet.packet_count += 1
    else:
        process_packet.packet_count = 1
        
    if process_packet.packet_count % 1000 == 0:
        now = time.time()
        stale_ips = []
        for ip, history in connection_history.items():
            if not history or (now - history[-1][0] > PORT_SCAN_WINDOW):
                stale_ips.append(ip)
        for ip in stale_ips:
            del connection_history[ip]

def start_monitoring(interface=None):
    logger.info("Starting intrusion monitor...")
    if interface:
        sniff(iface=interface, prn=process_packet, store=False)
    else:
        sniff(prn=process_packet, store=False)

if __name__ == "__main__":
    start_monitoring()
