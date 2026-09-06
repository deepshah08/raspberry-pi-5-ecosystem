import socket
import struct
import json
import subprocess
import argparse
import time
import os
import sys

def create_magic_packet(mac_address: str) -> bytes:
    """
    Constructs a standard 102-byte magic packet.
    6x 0xFF followed by 16x MAC address.
    """
    mac_address = mac_address.replace(':', '').replace('-', '').replace('.', '')
    
    if len(mac_address) != 12:
        raise ValueError("Invalid MAC address format")
    
    mac_bytes = bytes.fromhex(mac_address)
    
    return b'\xff' * 6 + mac_bytes * 16

class TargetRegistry:
    def __init__(self, registry_file: str = "targets.json"):
        self.registry_file = registry_file
        self.targets = self._load_registry()

    def _load_registry(self) -> dict:
        if not os.path.exists(self.registry_file):
            return {}
        try:
            with open(self.registry_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def save_registry(self):
        with open(self.registry_file, 'w') as f:
            json.dump(self.targets, f, indent=4)

    def get_target(self, name_or_mac: str) -> dict:
        for name, data in self.targets.items():
            if name == name_or_mac or data.get('mac') == name_or_mac:
                return data
        return {}

    def update_status(self, name_or_mac: str, status: str):
        for name, data in self.targets.items():
            if name == name_or_mac or data.get('mac') == name_or_mac:
                self.targets[name]['last_status'] = status
                self.save_registry()
                break


# Global variable for basic rate limiting
LAST_PACKET_TIME = 0.0
RATE_LIMIT_DELAY = 1.0  # seconds between packet dispatches

def send_magic_packet(mac_address: str, broadcast_ip: str = "255.255.255.255", port: int = 9):
    """
    Sends a magic packet to the given broadcast address.
    Enforces rate limiting to prevent broadcast storms.
    """
    global LAST_PACKET_TIME
    
    current_time = time.time()
    time_since_last = current_time - LAST_PACKET_TIME
    
    if time_since_last < RATE_LIMIT_DELAY:
        time.sleep(RATE_LIMIT_DELAY - time_since_last)
        
    packet = create_magic_packet(mac_address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast_ip, port))
        
    LAST_PACKET_TIME = time.time()

def verify_liveness(ip_address: str, timeout: int = 2) -> bool:
    """
    Pings the target IP to verify if it is online.
    """
    try:
        # -c 1 for 1 packet, -W timeout
        result = subprocess.run(
            ['ping', '-c', '1', '-W', str(timeout), ip_address],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False

def main():
    parser = argparse.ArgumentParser(description="Local Wake-on-LAN (WoL) Magic Packet Sentry")
    parser.add_argument('--wake', type=str, help="Target name or MAC address to wake")
    parser.add_argument('--list', action='store_true', help="List all known targets")
    parser.add_argument('--dry-run', action='store_true', help="Construct the magic packet but do not send it")
    parser.add_argument('--json', action='store_true', help="Output in JSON format")

    args = parser.parse_args()

    registry = TargetRegistry()

    if args.list:
        if args.json:
            print(json.dumps(registry.targets, indent=4))
        else:
            for name, data in registry.targets.items():
                print(f"{name}: MAC {data.get('mac')}, IP {data.get('ip')}, Status {data.get('last_status', 'unknown')}")
        return

    if args.wake:
        target = registry.get_target(args.wake)
        if target:
            mac = target.get('mac')
            ip = target.get('ip')
            broadcast = target.get('broadcast_address', '255.255.255.255')
        else:
            # Assume it's a MAC address
            mac = args.wake
            ip = None
            broadcast = '255.255.255.255'

        if not args.json:
            print(f"Targeting MAC: {mac}")

        if args.dry_run:
            if not args.json:
                print("Dry run mode: Packet not sent.")
            return

        send_magic_packet(mac, broadcast)
        
        if not args.json:
            print(f"Magic packet sent to {mac} via {broadcast}")
        
        if ip:
            if not args.json:
                print(f"Verifying liveness of {ip}...")
            time.sleep(1) # wait a moment before pinging, although WoL might take longer in reality. We'll do a basic check.
            
            is_online = False
            for _ in range(5):
                if verify_liveness(ip):
                    is_online = True
                    break
                time.sleep(1)

            status = "online" if is_online else "offline"
            registry.update_status(args.wake, status)
            
            if not args.json:
                print(f"Target is {status}")
            else:
                print(json.dumps({"target": args.wake, "mac": mac, "status": status}))

if __name__ == "__main__":
    main()
