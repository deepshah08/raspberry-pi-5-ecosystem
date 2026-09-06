import argparse
import json
import logging
import os
import requests
import sys
import time
from typing import Dict, List, Any
from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange

# Ensure project root is in path for project 56 import later
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import importlib.util

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Basic MAC OUI vendor mapping
OUI_VENDOR_MAP = {
    "B8:27:EB": "Raspberry Pi Foundation",
    "DC:A6:32": "Raspberry Pi Trading Ltd",
    "E4:5F:01": "Raspberry Pi Trading Ltd",
    "00:11:32": "Synology Incorporated",
    "00:1E:06": "WIBRAIN",
    "28:C6:3F": "Apple, Inc.",
    "00:14:22": "Dell Inc.",
    "00:1A:11": "Google, Inc.",
    "00:0C:29": "VMware, Inc."
}


PIHOLE_URLS = ["http://192.168.1.80/admin/api.php?getAllDHCPLeases", "http://192.168.1.92/admin/api.php?getAllDHCPLeases"]

def get_pihole_leases(dry_run: bool = False) -> Dict[str, dict]:
    if dry_run:
        return {"aa:bb:cc:dd:ee:ff": {"ip": "192.168.1.50", "hostname": "known-device"}}
    leases = {}
    for url in PIHOLE_URLS:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                for lease in data.get("leases", []):
                    leases[lease.get("MAC", "").lower()] = lease
        except Exception as e:
            logger.warning(f"Could not fetch DHCP leases from {url}: {e}")
    return leases

def alert_rogue_device(mac: str, ip: str, vendor: str, dry_run: bool = False):
    if dry_run:
        logger.info(f"[DRY RUN] Rogue device alert dispatched: MAC {mac} ({vendor}) at IP {ip}")
        return

    try:
        router_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../projects/56-notification-engine/router.py'))
        if os.path.exists(router_path):
            spec = importlib.util.spec_from_file_location("router", router_path)
            router_module = importlib.util.module_from_spec(spec)
            sys.modules["router"] = router_module
            spec.loader.exec_module(router_module)

            router = router_module.AlertRouter()
            severity = router_module.Severity.WARNING
            router.dispatch(source="Topology Mapper", title="Rogue Device Detected", body=f"Unknown MAC address {mac} ({vendor}) discovered at IP {ip}", severity=severity)
        else:
            logger.warning("Notification Engine not found, could not dispatch alert.")
    except Exception as e:
        logger.error(f"Failed to dispatch rogue device alert: {e}")

def get_vendor(mac: str) -> str:
    oui = mac[:8].upper()
    return OUI_VENDOR_MAP.get(oui, "Unknown Vendor")

def parse_arp_cache(dry_run: bool = False) -> List[Dict[str, str]]:
    devices = []

    if dry_run:
        # Return dummy data for dry run / testing
        return [
            {"ip": "192.168.1.10", "mac": "B8:27:EB:AA:BB:CC"},
            {"ip": "192.168.1.80", "mac": "00:11:32:11:22:33"},
            {"ip": "192.168.1.100", "mac": "FF:EE:DD:CC:BB:AA"}
        ]

    try:
        with open('/proc/net/arp', 'r') as f:
            lines = f.readlines()[1:] # skip header

        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                ip = parts[0]
                hw_type = parts[1]
                flags = parts[2]
                mac = parts[3]

                if mac != "00:00:00:00:00:00":
                    devices.append({"ip": ip, "mac": mac})
    except FileNotFoundError:
        logger.error("Could not read /proc/net/arp. Are you on Linux?")
    except Exception as e:
        logger.error(f"Error reading ARP cache: {e}")

    return devices

class ZeroconfListener:
    def __init__(self):
        self.hostnames: Dict[str, str] = {}

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info and info.addresses:
            import socket
            for addr in info.addresses:
                try:
                    ip = socket.inet_ntoa(addr)
                    # Use server name, strip the trailing dot and .local
                    hostname = info.server.rstrip('.').replace('.local', '') if info.server else name
                    self.hostnames[ip] = hostname
                except Exception:
                    pass

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.update_service(zc, type_, name)

def discover_hostnames(dry_run: bool = False) -> Dict[str, str]:
    if dry_run:
        return {
            "192.168.1.10": "pi-hole-node",
            "192.168.1.80": "ugreen-nas"
        }

    listener = ZeroconfListener()
    zeroconf = Zeroconf()
    services = ["_http._tcp.local.", "_workstation._tcp.local.", "_ssh._tcp.local."]
    browser = ServiceBrowser(zeroconf, services, listener)

    # Wait a bit for discovery
    time.sleep(2)

    zeroconf.close()
    return listener.hostnames

def load_devices(filepath: str) -> Dict[str, dict]:
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"Error loading devices from {filepath}: {e}")
        return {}

def save_devices(filepath: str, devices: Dict[str, dict]):
    try:
        with open(filepath, 'w') as f:
            json.dump(devices, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving devices to {filepath}: {e}")

def generate_mermaid(registry: Dict[str, dict]) -> str:
    lines = ["graph TD", "    Router[Gateway/Router]"]
    for mac, data in registry.items():
        if data["status"] == "active":
            node_id = mac.replace(":", "")
            label = f"{data['hostname']}<br>{data['ip']}<br>{data['vendor']}"
            lines.append(f"    Router --- {node_id}[\"{label}\"]")
    return "\n".join(lines)

def output_topology(registry: Dict[str, dict], output_dir: str, json_format: bool):
    if json_format:
        out_file = os.path.join(output_dir, "topology.json")
        with open(out_file, 'w') as f:
            json.dump(registry, f, indent=4)
        logger.info(f"Wrote JSON topology to {out_file}")
    else:
        out_file = os.path.join(output_dir, "topology.md")
        with open(out_file, 'w') as f:
            f.write("```mermaid\n" + generate_mermaid(registry) + "\n```")
        logger.info(f"Wrote Mermaid topology to {out_file}")

def main():
    parser = argparse.ArgumentParser(description="Homelab Network Topology Mapper & Device Discovery")
    parser.add_argument("--scan-now", action="store_true", help="Run a scan immediately")
    parser.add_argument("--output", type=str, help="Output directory for topology map", default=".")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode using dummy data")
    parser.add_argument("--json", action="store_true", help="Output topology in JSON format instead of Mermaid")

    args = parser.parse_args()

    devices_file = os.path.join(args.output, "devices.json")

    if args.scan_now:
        arp_devices = parse_arp_cache(args.dry_run)
        hostnames = discover_hostnames(args.dry_run)
        dhcp_leases = get_pihole_leases(args.dry_run)

        registry = load_devices(devices_file)

        current_time = time.time()

        for d in arp_devices:
            mac = d['mac']
            ip = d['ip']

            if mac not in registry:
                registry[mac] = {
                    "mac": mac,
                    "ip": ip,
                    "vendor": get_vendor(mac),
                    "hostname": hostnames.get(ip, "Unknown"),
                    "first_seen": current_time,
                    "last_seen": current_time,
                    "status": "active"
                }

                # Alert on new device discovery if it's not a known DHCP lease in Pi-hole
                mac_lower = mac.lower()
                if mac_lower not in dhcp_leases:
                    alert_rogue_device(mac, ip, registry[mac]["vendor"], args.dry_run)
            else:
                registry[mac]["last_seen"] = current_time
                registry[mac]["ip"] = ip # Update IP if it changed
                registry[mac]["status"] = "active"
                if ip in hostnames:
                    registry[mac]["hostname"] = hostnames[ip]

        # Mark stale devices
        for mac, data in registry.items():
            if current_time - data["last_seen"] > 3600: # 1 hour
                data["status"] = "offline"

        save_devices(devices_file, registry)
        logger.info(f"Updated registry with {len(registry)} devices.")

        output_topology(registry, args.output, args.json)

if __name__ == "__main__":
    main()
