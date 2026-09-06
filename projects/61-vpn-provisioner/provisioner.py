import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

import base64
import io
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
import qrcode

class Provisioner:
    def __init__(self, config_dir: str = "/etc/wireguard/clients"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.peers_file = self.config_dir / "peers.json"
        self._load_peers()

    def _load_peers(self) -> None:
        """Loads peers from the JSON database."""
        if self.peers_file.exists():
            with open(self.peers_file, "r") as f:
                try:
                    self.peers = json.load(f)
                except json.JSONDecodeError:
                    self.peers = {}
        else:
            self.peers = {}

    def _save_peers(self) -> None:
        """Saves peers to the JSON database."""
        with open(self.peers_file, "w") as f:
            json.dump(self.peers, f, indent=4)

    def generate_keypair(self) -> tuple[str, str]:
        """Generates an X25519 private and public key pair."""
        private_key = X25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return (
            base64.b64encode(private_bytes).decode('utf-8'),
            base64.b64encode(public_bytes).decode('utf-8')
        )

    def generate_psk(self) -> str:
        """Generates a pre-shared key."""
        return base64.b64encode(os.urandom(32)).decode('utf-8')

    def allocate_ip(self) -> str:
        """Allocates an IP address from 10.66.66.2 to 10.66.66.254."""
        used_ips = {peer_info['ip'] for peer_info in self.peers.values() if 'ip' in peer_info}
        for i in range(2, 255):
            ip = f"10.66.66.{i}"
            if ip not in used_ips:
                return ip
        raise RuntimeError("IP pool exhausted")

    def build_config(self, peer_name: str, private_key: str, psk: str, ip: str, dns: str = "192.168.1.80") -> str:
        """Builds a WireGuard client configuration string."""
        server_public_key = os.environ.get("WG_SERVER_PUBLIC_KEY", "SERVER_PUBLIC_KEY_PLACEHOLDER")
        endpoint = os.environ.get("WG_ENDPOINT", "vpn.example.com:51820")

        config = f"""[Interface]
PrivateKey = {private_key}
Address = {ip}/32
DNS = {dns}

[Peer]
PublicKey = {server_public_key}
PresharedKey = {psk}
AllowedIPs = 192.168.1.0/24, 10.66.66.0/24
Endpoint = {endpoint}
PersistentKeepalive = 25
"""
        return config

    def add_peer(self, peer_name: str, ip: Optional[str] = None, dns: str = "192.168.1.80") -> Dict[str, Any]:
        """Adds a new peer and generates its configuration."""
        if peer_name in self.peers:
            raise ValueError(f"Peer {peer_name} already exists")

        allocated_ip = ip if ip else self.allocate_ip()

        # Check IP collision
        used_ips = {peer_info['ip'] for peer_info in self.peers.values() if 'ip' in peer_info}
        if allocated_ip in used_ips:
            raise ValueError(f"IP {allocated_ip} is already in use")

        private_key, public_key = self.generate_keypair()
        psk = self.generate_psk()
        config_str = self.build_config(peer_name, private_key, psk, allocated_ip, dns)

        from datetime import datetime, timezone
        creation_date = datetime.now(timezone.utc).isoformat()

        peer_data = {
            "name": peer_name,
            "ip": allocated_ip,
            "public_key": public_key,
            "psk": psk,
            "dns": dns,
            "created_at": creation_date
        }

        self.peers[peer_name] = peer_data
        self._save_peers()

        config_file = self.config_dir / f"{peer_name}.conf"
        with open(config_file, "w") as f:
            f.write(config_str)

        return peer_data

    def generate_qr(self, peer_name: str, terminal: bool = False) -> Optional[str]:
        """Generates a QR code for a peer's configuration.
        Saves as PNG and optionally returns terminal ASCII string.
        """
        if peer_name not in self.peers:
            raise ValueError(f"Peer {peer_name} not found")

        config_file = self.config_dir / f"{peer_name}.conf"
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file for {peer_name} not found")

        with open(config_file, "r") as f:
            config_data = f.read()

        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(config_data)
        qr.make(fit=True)

        # Generate PNG
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(self.config_dir / f"{peer_name}.png")

        # Generate terminal output if requested
        if terminal:
            f = io.StringIO()
            qr.print_ascii(out=f)
            return f.getvalue()

        return None

    def revoke_peer(self, peer_name: str) -> None:
        """Revokes a peer by removing it from the database and deleting its config."""
        if peer_name not in self.peers:
            raise ValueError(f"Peer {peer_name} not found")

        del self.peers[peer_name]
        self._save_peers()

        config_file = self.config_dir / f"{peer_name}.conf"
        if config_file.exists():
            config_file.unlink()

        qr_file = self.config_dir / f"{peer_name}.png"
        if qr_file.exists():
            qr_file.unlink()


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Homelab WireGuard Dynamic Peer Provisioner", prog="vpnctl")
    parser.add_argument("--config-dir", type=str, default="/etc/wireguard/clients", help="Directory for client configs and peers database")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Add command
    parser_add = subparsers.add_parser("add", help="Add a new WireGuard peer")
    parser_add.add_argument("peer_name", type=str, help="Name of the peer")
    parser_add.add_argument("--ip", type=str, help="Specific IP to assign (optional)")
    parser_add.add_argument("--dns", type=str, default="192.168.1.80", help="DNS server for the client")

    # List command
    parser_list = subparsers.add_parser("list", help="List all enrolled peers")

    # QR command
    parser_qr = subparsers.add_parser("qr", help="Display terminal QR code for a peer")
    parser_qr.add_argument("peer_name", type=str, help="Name of the peer")

    # Revoke command
    parser_revoke = subparsers.add_parser("revoke", help="Revoke a peer and free its IP")
    parser_revoke.add_argument("peer_name", type=str, help="Name of the peer")

    args = parser.parse_args()

    provisioner = Provisioner(config_dir=args.config_dir)

    try:
        if args.command == "add":
            peer_data = provisioner.add_peer(args.peer_name, ip=args.ip, dns=args.dns)
            if args.json:
                print(json.dumps(peer_data, indent=2))
            else:
                print(f"Peer '{args.peer_name}' added successfully with IP {peer_data['ip']}.")
                provisioner.generate_qr(args.peer_name)
                print(f"Configuration and QR code saved to {args.config_dir}")

        elif args.command == "list":
            if args.json:
                print(json.dumps(provisioner.peers, indent=2))
            else:
                print(f"{'Name':<20} | {'IP':<15} | {'Created At'}")
                print("-" * 65)
                for name, data in provisioner.peers.items():
                    print(f"{name:<20} | {data.get('ip', 'N/A'):<15} | {data.get('created_at', 'N/A')}")

        elif args.command == "qr":
            qr_ascii = provisioner.generate_qr(args.peer_name, terminal=True)
            if args.json:
                print(json.dumps({"peer": args.peer_name, "status": "qr_generated"}))
            else:
                print(f"QR code for {args.peer_name}:\n")
                print(qr_ascii)

        elif args.command == "revoke":
            provisioner.revoke_peer(args.peer_name)
            if args.json:
                print(json.dumps({"peer": args.peer_name, "status": "revoked"}))
            else:
                print(f"Peer '{args.peer_name}' revoked successfully.")

    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
        else:
            print(f"Error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
