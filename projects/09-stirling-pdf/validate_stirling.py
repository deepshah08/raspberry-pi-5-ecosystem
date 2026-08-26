import yaml
import os

def validate_compose(filepath="docker-compose.stirling.yml"):
    if not os.path.exists(filepath):
        return False, f"{filepath} not found"
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        services = data.get('services', {})
        if 'stirling-pdf' not in services:
            return False, "stirling-pdf service missing"
        ports = services['stirling-pdf'].get('ports', [])
        if not any('8083:8080' in p for p in ports):
            return False, "Port 8083:8080 mapping missing"
        return True, "Stirling-PDF Compose configuration valid"
    except Exception as e:
        return False, str(e)
