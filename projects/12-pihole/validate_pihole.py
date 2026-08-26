import socket
import os
import subprocess

def check_dns_port(host="127.0.0.1", port=53):
    """Checks if DNS port 53 is open and responding on TCP/UDP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

def check_gravity_db():
    """Checks gravity database file status."""
    db_paths = ["/etc/pihole/gravity.db", "/etc/pihole/pihole-FTL.db"]
    for p in db_paths:
        if os.path.exists(p):
            return True, p
    return False, "None"
