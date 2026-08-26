import yaml
import os

def validate_n8n_compose(filepath="docker-compose.n8n.yml"):
    if not os.path.exists(filepath):
        return False, f"{filepath} not found"
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        services = data.get('services', {})
        if 'n8n' not in services:
            return False, "n8n service missing"
        ports = services['n8n'].get('ports', [])
        if not any('5678:5678' in str(p) for p in ports):
            return False, "Port 5678 mapping missing"
        return True, "n8n configuration valid"
    except Exception as e:
        return False, str(e)
