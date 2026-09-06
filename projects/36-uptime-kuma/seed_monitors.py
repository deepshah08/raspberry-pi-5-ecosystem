import os
import sys
import time
from uptime_kuma_api import UptimeKumaApi, MonitorType

KUMA_URL = os.getenv("KUMA_URL", "http://localhost:3001")
KUMA_USER = os.getenv("KUMA_USER", "admin")
KUMA_PASS = os.getenv("KUMA_PASS", "admin")

def connect_api():
    api = UptimeKumaApi(KUMA_URL)
    api.login(KUMA_USER, KUMA_PASS)
    return api

def main():
    try:
        api = connect_api()
        print("Connected to Uptime Kuma successfully.")

        nas_ip = "192.168.1.80"
        nas_services = [
            {"name": "Plex", "port": 32400, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:32400/web"},
            {"name": "Radarr", "port": 7878, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:7878"},
            {"name": "Sonarr", "port": 8989, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:8989"},
            {"name": "Prowlarr", "port": 9696, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:9696"},
            {"name": "Bazarr", "port": 6767, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:6767"},
            {"name": "qBittorrent", "port": 8080, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:8080"},
            {"name": "Overseerr", "port": 5055, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:5055"},
            {"name": "Vaultwarden", "port": 8085, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:8085"},
            {"name": "Pi-hole", "port": 8089, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:8089/admin"},
            {"name": "Homepage", "port": 3000, "type": MonitorType.HTTP, "url": f"http://{nas_ip}:3000"},
            {"name": "SMB", "port": 445, "type": MonitorType.PORT, "hostname": nas_ip},
        ]

        pi5_ip = "192.168.1.92"
        pi5_services = [
            {"name": "Secondary Pi-hole", "port": 80, "type": MonitorType.HTTP, "url": f"http://{pi5_ip}:80/admin"},
            {"name": "Unbound", "port": 5335, "type": MonitorType.PORT, "hostname": pi5_ip},
            {"name": "n8n", "port": 5678, "type": MonitorType.HTTP, "url": f"http://{pi5_ip}:5678"},
            {"name": "Jellyfin", "port": 8096, "type": MonitorType.HTTP, "url": f"http://{pi5_ip}:8096"},
            {"name": "Stirling-PDF", "port": 8083, "type": MonitorType.HTTP, "url": f"http://{pi5_ip}:8083"},
            {"name": "TripDrop", "port": 8088, "type": MonitorType.HTTP, "url": f"http://{pi5_ip}:8088"},
        ]

        gateway_ip = "192.168.1.254"
        gateway_services = [
            {"name": "Ping", "type": MonitorType.PING, "hostname": gateway_ip},
        ]

        all_services = [("NAS", s) for s in nas_services] + \
                       [("Pi 5", s) for s in pi5_services] + \
                       [("Gateway", s) for s in gateway_services]

        for prefix, service in all_services:
            try:
                if service["type"] == MonitorType.HTTP:
                    api.add_monitor(
                        type=MonitorType.HTTP,
                        name=f"{prefix} - {service['name']}",
                        url=service["url"]
                    )
                elif service["type"] == MonitorType.PORT:
                    api.add_monitor(
                        type=MonitorType.PORT,
                        name=f"{prefix} - {service['name']}",
                        hostname=service["hostname"],
                        port=service["port"]
                    )
                elif service["type"] == MonitorType.PING:
                    api.add_monitor(
                        type=MonitorType.PING,
                        name=f"{prefix} - {service['name']}",
                        hostname=service["hostname"]
                    )
                print(f"Added monitor for {prefix} - {service['name']}")
            except Exception as e:
                print(f"Failed to add monitor for {prefix} - {service['name']}: {e}")

        api.disconnect()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
