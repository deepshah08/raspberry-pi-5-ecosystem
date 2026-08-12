#!/bin/bash
# Plex + *arr Stack First-Run Setup
# Run this ONCE after filling in .env

set -e

# Change to the root of the stack directory (assuming the script is in scripts/)
cd "$(dirname "$0")/.."

echo "Starting first-run setup..."

# 1. Check .env exists and source it
if [ ! -f ".env" ]; then
    echo "Error: .env file not found in $(pwd)."
    echo "Please copy .env.example to .env and fill in the required values."
    exit 1
fi
echo "Sourcing .env file..."
set -a
source .env
set +a

# 2. Run validate_env.py — exit if fails
if [ -f "scripts/validate_env.py" ]; then
    echo "Validating environment variables..."
    python3 scripts/validate_env.py
else
    echo "Warning: scripts/validate_env.py not found. Skipping environment validation."
fi

# 3. Run init_nas_dirs.sh to create directory tree
if [ -f "scripts/init_nas_dirs.sh" ]; then
    echo "Initializing NAS directories..."
    bash scripts/init_nas_dirs.sh
else
    echo "Warning: scripts/init_nas_dirs.sh not found. Skipping directory initialization."
fi

# 4. docker compose pull (pull latest images)
echo "Pulling latest Docker images..."
docker compose pull

# 5. docker compose up -d (start all containers)
echo "Starting all Docker containers..."
docker compose up -d

# 6. Sleep 30 seconds for containers to initialize
echo "Waiting 30 seconds for containers to initialize..."
sleep 30

# 7. Run validate_stack.py — report which services are up
if [ -f "scripts/validate_stack.py" ]; then
    echo "Validating stack services..."
    python3 scripts/validate_stack.py
else
    echo "Warning: scripts/validate_stack.py not found. Skipping stack validation."
fi

# 8. Print next steps
PI5_IP=${PI5_IP:-$(hostname -I | awk '{print $1}')}

echo ""
echo "=========================================================="
echo "Setup Complete! Next Steps:"
echo "=========================================================="
echo " - Visit Plex at http://${PI5_IP}:32400"
echo " - Visit Prowlarr at http://${PI5_IP}:9696 to add indexers"
echo ""
echo " After setting up Prowlarr and grabbing API keys, run the following scripts:"
echo "   - python config/radarr_apply_config.py"
echo "   - python config/sonarr_apply_config.py"
echo "   - python config/bazarr_apply_config.py"
echo ""
echo " - Visit Overseerr at http://${PI5_IP}:5055 to set up request portal"
echo "=========================================================="