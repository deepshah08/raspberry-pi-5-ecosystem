import argparse
import base64
import ipaddress
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import qrcode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class WireGuardProvisioner:
    def __init__(self, config_dir: str):
        self.config_dir = Path(config_dir)
        self.peers_file = self.config_dir / 'peers.json'
        self.server_pubkey = "SERVER_PUBLIC_KEY_PLACEHOLDER" # Usually read from server conf
        self.server_endpoint = "vpn.example.com:51820" # Usually read from server conf
        self.subnet = ipaddress.IPv4Network('10.13.13.0/24')
        self.peers: Dict[str, Any] = {}

        # Ensure config dir exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.load_peers()

    def load_peers(self):
        """Loads the peers state from peers.json."""
        if self.peers_file.exists():
            try:
                with open(self.peers_file, 'r') as f:
                    self.peers = json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse {self.peers_file}. Starting fresh.")
                self.peers = {}
        else:
            self.peers = {}

    def save_peers(self):
        """Saves the current peers state to peers.json."""
        with open(self.peers_file, 'w') as f:
            json.dump(self.peers, f, indent=4)

    @staticmethod
    def generate_keypair() -> Tuple[str, str]:
        """Generates a Curve25519 private and public keypair."""
        private_key = x25519.X25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        priv_b64 = base64.b64encode(private_bytes).decode('utf-8')
        pub_b64 = base64.b64encode(public_bytes).decode('utf-8')
        return priv_b64, pub_b64

    @staticmethod
    def generate_preshared_key() -> str:
        """Generates a 32-byte pre-shared key."""
        return base64.b64encode(os.urandom(32)).decode('utf-8')

    def allocate_ip(self) -> str:
        """Allocates the next available IP address in the 10.13.13.0/24 subnet."""
        allocated_ips = {peer_info.get('ip') for peer_info in self.peers.values() if peer_info.get('ip')}

        # Start checking from .2 (assuming .1 is the server/gateway)
        for ip in self.subnet.hosts():
            ip_str = str(ip)
            # Skip .1 if we consider it the gateway
            if ip_str == '10.13.13.1':
                continue
            if ip_str not in allocated_ips:
                return ip_str

        raise ValueError("No available IP addresses in the subnet.")

    def generate_client_config(self, name: str, priv_key: str, psk: str, ip: str) -> str:
        """Generates a WireGuard client configuration file content."""
        config = f"""[Interface]
PrivateKey = {priv_key}
Address = {ip}/32
DNS = 10.13.13.1

[Peer]
PublicKey = {self.server_pubkey}
PresharedKey = {psk}
Endpoint = {self.server_endpoint}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
        return config

    def generate_qr_code(self, config_str: str, name: str, output_dir: Path):
        """Generates ASCII QR code for terminal and PNG QR code file."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(config_str)
        qr.make(fit=True)

        # Print ASCII QR
        print(f"\nQR Code for {name}:")
        qr.print_ascii(invert=True)

        # Save PNG
        img = qr.make_image(fill_color="black", back_color="white")
        png_path = output_dir / f"{name}.png"
        img.save(png_path)
        logger.info(f"Saved QR code PNG to {png_path}")

    def create_peer(self, name: str, dry_run: bool = False, json_output: bool = False):
        if name in self.peers:
            if json_output:
                print(json.dumps({"error": f"Peer '{name}' already exists."}))
            else:
                logger.error(f"Peer '{name}' already exists.")
            sys.exit(1)

        try:
            ip = self.allocate_ip()
        except ValueError as e:
            if json_output:
                print(json.dumps({"error": str(e)}))
            else:
                logger.error(str(e))
            sys.exit(1)

        priv_key, pub_key = self.generate_keypair()
        psk = self.generate_preshared_key()

        config_str = self.generate_client_config(name, priv_key, psk, ip)

        peer_data = {
            "name": name,
            "public_key": pub_key,
            "ip": ip,
            "status": "active"
        }

        if not dry_run:
            self.peers[name] = peer_data
            self.save_peers()

            # Save conf file
            conf_path = self.config_dir / f"{name}.conf"
            with open(conf_path, 'w') as f:
                f.write(config_str)
            if not json_output:
                logger.info(f"Saved client config to {conf_path}")
                self.generate_qr_code(config_str, name, self.config_dir)

        if json_output:
            print(json.dumps(peer_data))
        else:
            if dry_run:
                logger.info(f"[DRY RUN] Would create peer '{name}' with IP {ip}")
            else:
                logger.info(f"Successfully created peer '{name}' with IP {ip}")

    def list_peers(self, json_output: bool = False):
        if json_output:
            print(json.dumps(self.peers, indent=2))
        else:
            if not self.peers:
                print("No peers configured.")
                return
            print(f"{'Name':<20} {'IP':<15} {'Public Key':<45}")
            print("-" * 80)
            for name, data in self.peers.items():
                print(f"{name:<20} {data.get('ip', ''):<15} {data.get('public_key', ''):<45}")

    def remove_peer(self, name: str, dry_run: bool = False, json_output: bool = False):
        if name not in self.peers:
            if json_output:
                print(json.dumps({"error": f"Peer '{name}' not found."}))
            else:
                logger.error(f"Peer '{name}' not found.")
            sys.exit(1)
            return

        if not dry_run:
            del self.peers[name]
            self.save_peers()

            conf_path = self.config_dir / f"{name}.conf"
            png_path = self.config_dir / f"{name}.png"

            if conf_path.exists():
                conf_path.unlink()
            if png_path.exists():
                png_path.unlink()

        if json_output:
            print(json.dumps({"status": "success", "message": f"Removed peer {name}"}))
        else:
            if dry_run:
                logger.info(f"[DRY RUN] Would remove peer '{name}'")
            else:
                logger.info(f"Successfully removed peer '{name}' and associated files.")


def main():
    parser = argparse.ArgumentParser(description="Homelab Automated WireGuard Peer QR Code & Client Provisioner")
    parser.add_argument('--create-peer', type=str, help="Create a new peer with the given name")
    parser.add_argument('--list-peers', action='store_true', help="List all configured peers")
    parser.add_argument('--remove-peer', type=str, help="Remove a peer with the given name")
    parser.add_argument('--config-dir', type=str, default="/etc/wireguard/clients", help="Directory for config and state files")
    parser.add_argument('--dry-run', action='store_true', help="Do not write any files or modify state")
    parser.add_argument('--json', action='store_true', help="Output in JSON format")

    args = parser.parse_args()

    config_dir = args.config_dir
    try:
        Path(config_dir).mkdir(parents=True, exist_ok=True)
    except PermissionError:
        if args.json:
            print(json.dumps({"error": f"Permission denied to create or access config directory: {config_dir}"}))
        else:
            logger.error(f"Permission denied to create or access config directory: {config_dir}")
        sys.exit(1)

    provisioner = WireGuardProvisioner(config_dir)

    if args.create_peer:
        provisioner.create_peer(args.create_peer, dry_run=args.dry_run, json_output=args.json)
    elif args.list_peers:
        provisioner.list_peers(json_output=args.json)
    elif args.remove_peer:
        provisioner.remove_peer(args.remove_peer, dry_run=args.dry_run, json_output=args.json)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
