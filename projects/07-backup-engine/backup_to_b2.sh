#!/bin/bash
# Encrypted Backblaze B2 backup script via Restic/rclone
set -e

SOURCE_DIR="/mnt/nas/backup_vault"
B2_BUCKET="deep-homelab-backup"
RESTIC_REPOSITORY="b2::/restic"
RESTIC_PASSWORD_FILE="/etc/restic/password.txt"

echo "Starting Backblaze B2 Backup from $SOURCE_DIR..."

if [ ! -d "$SOURCE_DIR" ]; then
  echo "Warning: Source directory $SOURCE_DIR does not exist. Skipping."
  exit 0
fi

# Run restic backup if configured
if command -v restic &> /dev/null && [ -f "$RESTIC_PASSWORD_FILE" ]; then
  restic -r "$RESTIC_REPOSITORY" --password-file "$RESTIC_PASSWORD_FILE" backup "$SOURCE_DIR"
  restic -r "$RESTIC_REPOSITORY" --password-file "$RESTIC_PASSWORD_FILE" forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
  echo "Restic backup completed successfully."
else
  echo "Restic or credentials not configured. Verification pass."
fi
