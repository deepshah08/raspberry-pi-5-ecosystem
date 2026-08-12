#!/usr/bin/env python3

import socket
import subprocess
import os
import sys

def check_port(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            return result == 0
    except Exception:
        return False

def check_path(path):
    return os.path.exists(path)

def check_docker():
    try:
        result = subprocess.run(["docker", "ps"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def main():
    services = {
        "Plex": 32400,
        "Radarr": 7878,
        "Sonarr": 8989,
        "Prowlarr": 9696,
        "qBittorrent": 8080,
        "Bazarr": 6767,
        "Overseerr": 5055,
        "Tautulli": 8181
    }

    paths = [
        "/mnt/nas/media/movies",
        "/mnt/nas/media/tv",
        "/mnt/nas/media/downloads"
    ]

    all_passed = True

    print(f"{'Service':<15} | {'Port':<6} | {'Status'}")
    print("-" * 35)
    
    for service, port in services.items():
        is_open = check_port("localhost", port)
        status = "✅" if is_open else "❌"
        if not is_open:
            all_passed = False
        print(f"{service:<15} | {port:<6} | {status}")
    
    print("
Paths Check:")
    for path in paths:
        exists = check_path(path)
        status = "✅" if exists else "❌"
        if not exists:
            all_passed = False
        print(f"{path:<30} | {status}")
        
    print("
Docker Check:")
    docker_running = check_docker()
    status = "✅" if docker_running else "❌"
    if not docker_running:
        all_passed = False
    print(f"{'docker ps':<30} | {status}")
    
    if all_passed:
        print("
All checks passed! ✅")
        sys.exit(0)
    else:
        print("
Some checks failed! ❌")
        sys.exit(1)

if __name__ == "__main__":
    main()
