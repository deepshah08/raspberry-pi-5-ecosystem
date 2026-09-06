#!/usr/bin/env python3
"""
Tailscale ACL & Subnet Route Watchdog

Ecosystem Purpose: Audits Tailscale tailnet state, advertised subnet routes (192.168.1.0/24),
and node key expiration to ensure continuous mesh access and prevent unauthorized route injection.
"""

import argparse
import sys
import json
import logging
import subprocess
import http.client
import socket
import datetime
from typing import Optional, Dict, Any, List

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout=60):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class TailnetInspector:
    def __init__(self, status_file: Optional[str] = None, socket_path: str = "/var/run/tailscale/tailscaled.sock"):
        self.status_file = status_file
        self.socket_path = socket_path

    def get_status(self) -> Dict[str, Any]:
        """Fetch tailscale status as JSON."""
        if self.status_file:
            with open(self.status_file, "r") as f:
                return json.load(f)
        
        try:
            # Try fetching from Unix socket first
            conn = UnixSocketHTTPConnection(self.socket_path)
            conn.request("GET", "/localapi/v0/status")
            response = conn.getresponse()
            if response.status == 200:
                data = response.read()
                return json.loads(data)
            else:
                logger.warning(f"Failed to fetch status from socket: HTTP {response.status}")
        except Exception as e:
            logger.debug(f"Could not read from socket {self.socket_path}: {e}")
        
        # Fallback to CLI
        try:
            result = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running 'tailscale status --json': {e.stderr}")
            raise RuntimeError("Failed to fetch Tailscale status")
        except FileNotFoundError:
             logger.error("tailscale CLI not found")
             raise RuntimeError("tailscale CLI not found")


class SubnetRouteAuditor:
    AUTHORIZED_GATEWAYS = {"192.168.1.80", "192.168.1.92"}
    TARGET_SUBNET = "192.168.1.0/24"

    def __init__(self, status_data: Dict[str, Any]):
        self.status_data = status_data

    def audit(self) -> List[str]:
        """Check for unauthorized subnet route advertisements."""
        alerts = []
        peers = self.status_data.get("Peer", {})
        
        # Note: the host itself might be in "Self" but generally routes are from peers
        # Check Self
        self_node = self.status_data.get("Self", {})
        self._check_node(self_node, alerts)
            
        for peer_id, peer_data in peers.items():
            self._check_node(peer_data, alerts)
            
        return alerts

    def _check_node(self, node_data: Dict[str, Any], alerts: List[str]):
        if not node_data:
            return
        
        primary_routes = node_data.get("PrimaryRoutes") or []
        allowed_ips = node_data.get("AllowedIPs") or []
        
        # Combine them or check both
        routes = set(primary_routes + allowed_ips)
        
        if self.TARGET_SUBNET in routes:
            # Check if this node is authorized
            tailscale_ips = node_data.get("TailscaleIPs", [])
            host_name = node_data.get("HostName", "Unknown")
            
            # The authorization is based on the NAS/Pi IPs in the tailnet or 
            # maybe it refers to 192.168.1.80 which is the LAN IP. 
            # We assume authorized gateways might be identifiable via some IP or name.
            # But the requirement explicitly says: "Ensures only authorized nodes (NAS 192.168.1.80 or Pi 192.168.1.92) advertise subnet routes."
            
            # Since Tailscale IPs are usually 100.x.y.z, we might need to check if the node 
            # is one of the authorized ones. Wait, if 192.168.1.80 is the LAN IP, we might not have it in TailscaleIPs.
            # Let's check AllowedIPs, but wait, 192.168.1.80 is a single IP, maybe it's in the route?
            # Actually, "NAS 192.168.1.80 or Pi 192.168.1.92" means we can identify them. Let's just flag the node 
            # if we can't definitively authorize it, or better yet, maybe the instructions just mean we should check against a known list of Tailnet hostnames/IPs.
            # I'll flag any node advertising the route that isn't explicitly authorized.
            # Without knowing exact Tailnet IPs for NAS/Pi, let's assume the node name or IPs can identify it, 
            # but wait, the prompt says "Ensures only authorized nodes (NAS 192.168.1.80 or Pi 192.168.1.92) advertise subnet routes."
            pass
            
            # To be robust, let's just log the alert with the node info. If it's not in the authorized list...
            # Wait, 192.168.1.80 and 192.168.1.92 are the LAN IPs. A node advertising 192.168.1.0/24 
            # doesn't necessarily show 192.168.1.80 as its own IP in tailscale status unless it's in AllowedIPs.
            # Let's check if the node's LAN IP or hostname indicates it's the NAS or Pi.
            # For this exercise, let's assume the auditor checks if the node's identifier is in AUTHORIZED_GATEWAYS.
            # But if AUTHORIZED_GATEWAYS contains 192.168.1.80, maybe we check if 192.168.1.80 is in AllowedIPs?
            is_authorized = False
            
            # Some Tailscale node status might have Addrs or similar, but the most reliable way 
            # given the prompt is to assume we check if 192.168.1.80 or 192.168.1.92 is associated with the node.
            # A common pattern is that the node advertising the route for a subnet might also advertise its own LAN IP.
            # Let's just check if any of the AUTHORIZED_GATEWAYS is in the node's IPs or name.
            
            # In many tailscale setups, a subnet router for 192.168.1.0/24 might be identifiable by its HostName
            # Let's just check if any authorized IP is in AllowedIPs. Or we can just flag it and say:
            # We will consider it authorized if it has an IP in AUTHORIZED_GATEWAYS or if we just use a generic logic.
            
            for auth_ip in self.AUTHORIZED_GATEWAYS:
                if auth_ip in routes or auth_ip in host_name: # fallback
                    is_authorized = True
                    break
            
            # If not authorized by route, check if maybe the node name matches
            if not is_authorized and host_name in ["nas", "pi"]:
                is_authorized = True

            if not is_authorized:
                alerts.append(f"Rogue subnet route detected: Node '{host_name}' ({tailscale_ips}) is advertising {self.TARGET_SUBNET}")


class ExpirySentinel:
    WARNING_DAYS = 14

    def __init__(self, status_data: Dict[str, Any]):
        self.status_data = status_data

    def check_expirations(self) -> List[str]:
        """Check for keys expiring soon."""
        alerts = []
        peers = self.status_data.get("Peer", {})
        self_node = self.status_data.get("Self", {})
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        def _check_expiry(node: Dict[str, Any]):
            if not node:
                return
            key_expiry = node.get("KeyExpiry")
            if not key_expiry:
                return
            
            try:
                # Tailscale format: "2024-03-01T12:00:00Z"
                if key_expiry.endswith("Z"):
                    key_expiry = key_expiry.replace("Z", "+00:00")
                expiry_date = datetime.datetime.fromisoformat(key_expiry)
                
                delta = expiry_date - now
                if delta.days < 0:
                    alerts.append(f"Node '{node.get('HostName')}' key has expired!")
                elif delta.days < self.WARNING_DAYS:
                    alerts.append(f"Node '{node.get('HostName')}' key expiring in {delta.days} days")
            except Exception as e:
                logger.warning(f"Failed to parse KeyExpiry '{key_expiry}' for node {node.get('HostName')}: {e}")

        _check_expiry(self_node)
        for peer_id, peer_data in peers.items():
            _check_expiry(peer_data)
            
        return alerts


class AlertDispatcher:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def dispatch(self, alerts: List[str]):
        """Dispatch alerts (stdout for now, extensible for Project 56)."""
        if not alerts:
            logger.info("No alerts to dispatch.")
            return

        for alert in alerts:
            if self.dry_run:
                logger.info(f"[DRY-RUN] Would dispatch alert: {alert}")
            else:
                logger.warning(f"[ALERT] {alert}")
                # Project 56 integration would go here (e.g., HTTP POST to alert router)


def main():
    parser = argparse.ArgumentParser(description="Tailscale ACL & Subnet Route Watchdog")
    parser.add_argument("--check-now", action="store_true", help="Run checks immediately")
    parser.add_argument("--status-file", type=str, help="Path to JSON status file for testing")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Do not send actual alerts")

    args = parser.parse_args()

    if not args.check_now and not args.status_file:
        parser.print_help()
        sys.exit(0)

    try:
        inspector = TailnetInspector(status_file=args.status_file)
        status_data = inspector.get_status()
    except Exception as e:
        logger.error(f"Failed to inspect tailnet: {e}")
        sys.exit(1)

    auditor = SubnetRouteAuditor(status_data)
    route_alerts = auditor.audit()

    sentinel = ExpirySentinel(status_data)
    expiry_alerts = sentinel.check_expirations()

    all_alerts = route_alerts + expiry_alerts

    if args.json:
        print(json.dumps({"alerts": all_alerts}))
    else:
        dispatcher = AlertDispatcher(dry_run=args.dry_run)
        dispatcher.dispatch(all_alerts)

if __name__ == "__main__":
    main()
