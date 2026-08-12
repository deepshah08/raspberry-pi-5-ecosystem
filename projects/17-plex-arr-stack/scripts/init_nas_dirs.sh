#!/bin/bash

# Define directories
DIRS=(
    "/mnt/nas/media/movies"
    "/mnt/nas/media/tv"
    "/mnt/nas/media/downloads/complete"
    "/mnt/nas/media/downloads/incomplete"
    "/mnt/nas/configs/plex"
    "/mnt/nas/configs/radarr"
    "/mnt/nas/configs/sonarr"
    "/mnt/nas/configs/prowlarr"
    "/mnt/nas/configs/bazarr"
    "/mnt/nas/configs/qbittorrent"
    "/mnt/nas/configs/overseerr"
    "/mnt/nas/configs/tautulli"
)

# Warn if /mnt/nas is not mounted
if ! mountpoint -q /mnt/nas; then
    echo "WARNING: /mnt/nas is not a mountpoint!"
fi

created_count=0

# Loop through and create
for dir in "${DIRS[@]}"; do
    if mkdir -p "$dir"; then
        if chown 1000:1000 "$dir"; then
            if chmod 755 "$dir"; then
                echo "SUCCESS: Created and set permissions for $dir"
                ((created_count++))
            else
                echo "FAILURE: Failed to set permissions for $dir"
            fi
        else
            echo "FAILURE: Failed to set ownership for $dir"
        fi
    else
        echo "FAILURE: Failed to create directory $dir"
    fi
done

echo "Total directories successfully processed: $created_count out of ${#DIRS[@]}"
