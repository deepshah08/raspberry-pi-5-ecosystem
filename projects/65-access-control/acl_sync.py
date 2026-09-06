import argparse
import json
import logging
import ipaddress
from typing import List
from pathlib import Path
import subprocess

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

TRUSTED_SUBNETS = ["192.168.1.0/24"]

def parse_peers_file(peers_file: Path) -> List[str]:
    """Reads and parses the peers JSON file returning a list of valid IPs/CIDRs."""
    if not peers_file.exists():
        logging.warning(f"Peers file {peers_file} does not exist.")
        return []

    try:
        with open(peers_file, "r") as f:
            peers_data = json.load(f)
    except json.JSONDecodeError:
        logging.error(f"Failed to decode JSON from {peers_file}.")
        return []

    ips = []
    for peer_name, data in peers_data.items():
        ip = data.get("ip")
        if ip:
            ips.append(ip)
    return ips

def validate_cidrs(ips: List[str]) -> List[str]:
    """Validates IPs/CIDRs using ipaddress and returns a list of valid strings."""
    valid_cidrs = []
    for ip in ips:
        try:
            # this parses both ipv4 and ipv6 addresses and networks
            ip_obj = ipaddress.ip_network(ip, strict=False)
            valid_cidrs.append(str(ip_obj))
        except ValueError:
            logging.error(f"Invalid IP/CIDR skipped: {ip}")
    return valid_cidrs

def generate_nginx_snippet(cidrs: List[str]) -> str:
    """Generates the Nginx access restriction snippet."""
    lines = []
    lines.append("# Dynamic ACL Snippet")
    for cidr in cidrs:
        lines.append(f"allow {cidr};")
    lines.append("deny all;")
    return "\n".join(lines) + "\n"

def main():
    parser = argparse.ArgumentParser(description="Zero-Trust Access Control & Reverse Proxy Allowlist Synchronizer")
    parser.add_argument("--peers-file", type=str, required=True, help="Path to the JSON peers file")
    parser.add_argument("--output", type=str, required=True, help="Path to the output Nginx snippet")
    parser.add_argument("--dry-run", action="store_true", help="Print the snippet without writing to file")
    parser.add_argument("--reload-nginx", action="store_true", help="Simulate reloading Nginx")

    args = parser.parse_args()

    peers_file_path = Path(args.peers_file)
    output_path = Path(args.output)

    peer_ips = parse_peers_file(peers_file_path)

    # Merge with trusted local LAN subnets
    all_ips = TRUSTED_SUBNETS + peer_ips

    valid_cidrs = validate_cidrs(all_ips)

    # Generate Nginx snippet
    nginx_snippet = generate_nginx_snippet(valid_cidrs)

    if args.dry_run:
        logging.info("Dry run mode. Generated snippet:")
        print(nginx_snippet)
    else:
        # Create parent directories if they don't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(output_path, "w") as f:
                f.write(nginx_snippet)
            logging.info(f"Successfully wrote snippet to {output_path}")
        except IOError as e:
            logging.error(f"Failed to write snippet to {output_path}: {e}")
            return

    if args.reload_nginx:
        logging.info("Reloading Nginx...")
        if not args.dry_run:
            # Simulate reloading Nginx or actually do it if needed
            # In a real setup, we might run `nginx -s reload` or restart a container
            logging.info("Nginx reload triggered (simulated).")
        else:
            logging.info("Dry run mode: Skipping actual Nginx reload.")

if __name__ == "__main__":
    main()
