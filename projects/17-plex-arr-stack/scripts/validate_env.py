#!/usr/bin/env python3
import os
import sys
from pathlib import Path

def parse_env_file(filepath):
    env_vars = {}
    if not os.path.exists(filepath):
        return env_vars
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            # Ignore empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Split on first equals sign
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                # Remove inline comments and strip quotes
                value = value.split('#', 1)[0].strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                env_vars[key] = value
                
    return env_vars

def main():
    script_dir = Path(__file__).resolve().parent
    env_file = script_dir.parent / '.env'
    
    print(f"Validating {env_file}...
")
    
    if not env_file.exists():
        print(f"❌ .env file not found at {env_file}")
        sys.exit(1)
        
    env_vars = parse_env_file(env_file)
    
    required_vars = [
        "PUID", 
        "PGID", 
        "TZ", 
        "MEDIA_PATH", 
        "CONFIG_PATH", 
        "PLEX_CLAIM", 
        "VPN_SERVICE_PROVIDER", 
        "OPENVPN_USER", 
        "OPENVPN_PASSWORD"
    ]
    
    all_passed = True
    
    print("Checking required variables:")
    for var in required_vars:
        value = env_vars.get(var)
        if value:
            print(f"✅ {var} is set")
        else:
            print(f"❌ {var} is missing or empty")
            all_passed = False
            
    print("
Checking directories:")
    media_path = env_vars.get("MEDIA_PATH")
    if media_path:
        if os.path.isdir(media_path):
            print(f"✅ MEDIA_PATH ({media_path}) exists")
        else:
            print(f"❌ MEDIA_PATH ({media_path}) does not exist")
            all_passed = False
            
    config_path = env_vars.get("CONFIG_PATH")
    if config_path:
        if os.path.isdir(config_path):
            print(f"✅ CONFIG_PATH ({config_path}) exists")
        else:
            print(f"❌ CONFIG_PATH ({config_path}) does not exist")
            all_passed = False
            
    print("
Validation Result:")
    if all_passed:
        print("✅ All checks passed!")
        sys.exit(0)
    else:
        print("❌ Validation failed. Please fix the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
