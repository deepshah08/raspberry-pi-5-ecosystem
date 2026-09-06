import argparse
import sys
import logging
import sqlite3
import time
import os
import tarfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import secrets
from prometheus_client import start_http_server, Gauge
import json

# Prometheus Metrics
BACKUP_SUCCESS = Gauge('homelab_vaultwarden_backup_success', '1 if backup succeeded, 0 otherwise')
DB_SIZE_BYTES = Gauge('homelab_vaultwarden_db_size_bytes', 'Size of the Vaultwarden database in bytes')
ATTACHMENTS_TOTAL = Gauge('homelab_vaultwarden_attachments_total', 'Total number of attachments')

def get_encryption_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
        backend=default_backend()
    )
    return kdf.derive(passphrase.encode())

def encrypt_file(file_path: str, passphrase: str) -> str:
    salt = secrets.token_bytes(16)
    key = get_encryption_key(passphrase, salt)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)

    with open(file_path, "rb") as f:
        data = f.read()

    ct = aesgcm.encrypt(nonce, data, None)

    encrypted_path = file_path + ".enc"
    with open(encrypted_path, "wb") as f:
        f.write(salt)
        f.write(nonce)
        f.write(ct)

    return encrypted_path

def backup_sqlite(source_db_path: str, target_db_path: str, pages: int = 250, sleep_time: float = 0.010) -> bool:
    try:
        source = sqlite3.connect(source_db_path)
        target = sqlite3.connect(target_db_path)

        with target:
            source.backup(target, pages=pages, sleep=sleep_time)

        source.close()
        target.close()
        return True
    except sqlite3.Error as e:
        logging.error(f"SQLite backup failed: {e}")
        return False

def package_and_encrypt_backup(db_path: str, passphrase: str, output_dir: str = ".") -> str:
    db_path_obj = Path(db_path)
    backup_db_path = Path(output_dir) / f"{db_path_obj.stem}_backup.sqlite3"

    # 1. Non-blocking SQLite backup
    success = backup_sqlite(str(db_path_obj), str(backup_db_path))
    if not success:
        BACKUP_SUCCESS.set(0)
        raise RuntimeError("SQLite backup failed")

    # 2. Compress into tar.gz
    archive_path = Path(output_dir) / f"{db_path_obj.stem}_backup.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(backup_db_path, arcname=backup_db_path.name)

    # Clean up intermediate backup db
    backup_db_path.unlink(missing_ok=True)

    # 3. Encrypt archive
    encrypted_path = encrypt_file(str(archive_path), passphrase)

    # Clean up intermediate archive
    archive_path.unlink(missing_ok=True)

    BACKUP_SUCCESS.set(1)

    # Set DB size metric
    if db_path_obj.exists():
        DB_SIZE_BYTES.set(db_path_obj.stat().st_size)

    return encrypted_path

def audit_attachments(attachments_dir: str, max_size_mb: int = 50) -> list:
    oversized_files = []
    total_attachments = 0
    attachments_path = Path(attachments_dir)

    if attachments_path.exists() and attachments_path.is_dir():
        for file_path in attachments_path.rglob("*"):
            if file_path.is_file():
                total_attachments += 1
                size_mb = file_path.stat().st_size / (1024 * 1024)
                if size_mb > max_size_mb:
                    oversized_files.append({
                        "file": str(file_path),
                        "size_mb": round(size_mb, 2)
                    })

    ATTACHMENTS_TOTAL.set(total_attachments)
    return oversized_files

def parse_args(args=None):
    parser = argparse.ArgumentParser(description="Vaultwarden Secrets Sentinel & Backup Manager")
    parser.add_argument("--audit-now", action="store_true", help="Run attachment audit now")
    parser.add_argument("--backup-now", action="store_true", help="Run SQLite backup and encrypt now")
    parser.add_argument("--db-path", type=str, help="Path to Vaultwarden SQLite database", default="/volume2/docker/vaultwarden/db.sqlite3")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without modifying files")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--passphrase", type=str, help="Emergency passphrase for encryption", default="default_emergency_passphrase")
    parser.add_argument("--output-dir", type=str, help="Output directory for backup", default=".")
    parser.add_argument("--attachments-dir", type=str, help="Path to attachments directory", default="/volume2/docker/vaultwarden/attachments")
    parser.add_argument("--exporter-port", type=int, help="Prometheus exporter port", default=9126)
    parser.add_argument("--daemon", action="store_true", help="Run as daemon exposing metrics")
    return parser.parse_args(args)

def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO)

    results = {}

    if args.audit_now:
        if args.dry_run:
            logging.info(f"DRY RUN: Would audit attachments in {args.attachments_dir}")
        else:
            oversized = audit_attachments(args.attachments_dir)
            if oversized:
                logging.warning(f"Found {len(oversized)} oversized attachments: {oversized}")
            else:
                logging.info("Attachment audit passed, no oversized files found.")
            results["oversized_attachments"] = oversized

    if args.backup_now:
        if args.dry_run:
            logging.info(f"DRY RUN: Would backup {args.db_path} to {args.output_dir} and encrypt")
        else:
            logging.info(f"Starting backup for {args.db_path}")
            try:
                enc_path = package_and_encrypt_backup(args.db_path, args.passphrase, args.output_dir)
                logging.info(f"Backup successful: {enc_path}")
                results["backup_path"] = enc_path
            except Exception as e:
                logging.error(f"Backup failed: {e}")
                results["backup_error"] = str(e)

    if args.json:
        print(json.dumps(results, indent=2))

    if args.daemon:
        start_http_server(args.exporter_port)
        logging.info(f"Started Prometheus exporter on port {args.exporter_port}")
        while True:
            time.sleep(10)

if __name__ == "__main__":
    main()
