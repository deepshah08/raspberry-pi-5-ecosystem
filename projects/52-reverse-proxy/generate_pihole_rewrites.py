#!/usr/bin/env python3
import argparse
import re
import sys
import os

def parse_nginx_domains(nginx_conf_path):
    """Parses an nginx.conf file for server_name directives ending in .home"""
    domains = set()
    try:
        with open(nginx_conf_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: Nginx config file not found at {nginx_conf_path}", file=sys.stderr)
        return list(domains)

    # Simple regex to find server_name followed by spaces, then domains, ending with a semicolon
    server_name_regex = re.compile(r'server_name\s+([^;]+);')
    matches = server_name_regex.findall(content)

    for match in matches:
        names = match.split()
        for name in names:
            if name.endswith('.home'):
                domains.add(name)

    return sorted(list(domains))

def generate_pihole_records(domains, target_ip):
    """Generates pi-hole custom.list format strings"""
    records = []
    for domain in domains:
        records.append(f"{target_ip} {domain}")
    return records

def main():
    parser = argparse.ArgumentParser(description="Generate Pi-hole custom.list rewrites from nginx.conf")
    parser.add_argument('--nginx-conf', type=str, default='nginx.conf', help='Path to nginx.conf (default: nginx.conf)')
    parser.add_argument('--target-ip', type=str, required=True, help='Target IP for local domains (e.g., 192.168.1.80)')
    parser.add_argument('--output', type=str, help='Output file path for Pi-hole custom.list records')
    parser.add_argument('--dry-run', action='store_true', help='Print records to stdout without writing to file')

    args = parser.parse_args()

    domains = parse_nginx_domains(args.nginx_conf)
    if not domains:
        print(f"No .home domains found in {args.nginx_conf}", file=sys.stderr)
        sys.exit(1)

    records = generate_pihole_records(domains, args.target_ip)

    output_text = "\n".join(records) + "\n"

    if args.dry_run:
        print("Dry run mode. Generated records:")
        print(output_text, end="")
    elif args.output:
        try:
            with open(args.output, 'w') as f:
                f.write(output_text)
            print(f"Successfully wrote {len(records)} records to {args.output}")
        except Exception as e:
            print(f"Error writing to {args.output}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # If not dry run and no output, default to printing
        print(output_text, end="")

if __name__ == '__main__':
    main()
