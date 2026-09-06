import sys
from pathlib import Path
import sqlite3
import os
import tarfile
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vault_sentinel import (
    package_and_encrypt_backup,
    get_encryption_key,
    audit_attachments,
    parse_args
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    cursor.execute("INSERT INTO users (name) VALUES ('admin')")
    conn.commit()
    conn.close()
    return db_path

def test_backup_and_encrypt(temp_db, tmp_path):
    passphrase = "test_passphrase"
    enc_path = package_and_encrypt_backup(str(temp_db), passphrase, str(tmp_path))

    assert Path(enc_path).exists()
    assert enc_path.endswith(".enc")

    # Decrypt and verify
    with open(enc_path, "rb") as f:
        salt = f.read(16)
        nonce = f.read(12)
        ct = f.read()

    key = get_encryption_key(passphrase, salt)
    aesgcm = AESGCM(key)
    data = aesgcm.decrypt(nonce, ct, None)

    decrypted_archive_path = tmp_path / "test_decrypted.tar.gz"
    with open(decrypted_archive_path, "wb") as f:
        f.write(data)

    with tarfile.open(decrypted_archive_path, "r:gz") as tar:
        members = tar.getnames()
        assert "test_backup.sqlite3" in members
        tar.extractall(path=tmp_path)

    extracted_db = tmp_path / "test_backup.sqlite3"
    assert extracted_db.exists()

    conn = sqlite3.connect(extracted_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM users")
    assert cursor.fetchone()[0] == 'admin'
    conn.close()

def test_audit_attachments(tmp_path):
    attach_dir = tmp_path / "attachments"
    attach_dir.mkdir()

    # Create small file
    small_file = attach_dir / "small.txt"
    small_file.write_bytes(b"0" * 1024) # 1 KB

    # Create large file (>50MB)
    large_file = attach_dir / "large.txt"
    large_file.write_bytes(b"0" * (51 * 1024 * 1024)) # 51 MB

    oversized = audit_attachments(str(attach_dir), max_size_mb=50)

    assert len(oversized) == 1
    assert "large.txt" in oversized[0]["file"]
    assert oversized[0]["size_mb"] > 50

def test_parse_args():
    args = parse_args(["--backup-now", "--db-path", "/test/db.sqlite3", "--passphrase", "secret"])
    assert args.backup_now is True
    assert args.db_path == "/test/db.sqlite3"
    assert args.passphrase == "secret"
    assert args.json is False

    args2 = parse_args(["--audit-now", "--json", "--attachments-dir", "/data/attachments"])
    assert args2.audit_now is True
    assert args2.json is True
    assert args2.attachments_dir == "/data/attachments"

from vault_sentinel import BACKUP_SUCCESS, DB_SIZE_BYTES, ATTACHMENTS_TOTAL
def test_prometheus_metrics(temp_db, tmp_path):
    attach_dir = tmp_path / "attachments"
    attach_dir.mkdir()

    # Trigger attachment audit
    small_file = attach_dir / "small.txt"
    small_file.write_bytes(b"0" * 1024)
    audit_attachments(str(attach_dir))
    assert ATTACHMENTS_TOTAL._value.get() == 1

    # Trigger backup
    package_and_encrypt_backup(str(temp_db), "secret", str(tmp_path))
    assert BACKUP_SUCCESS._value.get() == 1
    assert DB_SIZE_BYTES._value.get() > 0
