import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import datetime
import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from cert_renewer import check_needs_renewal, renew_certificate

def generate_ca():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"Test CA"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None), critical=True,
    ).sign(private_key, hashes.SHA256(), default_backend())

    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    return cert_bytes, key_bytes


def generate_cert(ca_cert_bytes, ca_key_bytes, days_valid, include_san=True):
    ca_cert = x509.load_pem_x509_certificate(ca_cert_bytes, default_backend())
    ca_key = serialization.load_pem_private_key(ca_key_bytes, password=None, backend=default_backend())

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"test.local"),
    ])
    
    builder = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        ca_cert.subject
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_valid)
    )

    if include_san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"test.local"), x509.DNSName(u"www.test.local")]),
            critical=False,
        )

    cert = builder.sign(ca_key, hashes.SHA256(), default_backend())

    cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
    key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    return cert_bytes, key_bytes

@pytest.fixture
def temp_env(tmp_path):
    ca_cert_bytes, ca_key_bytes = generate_ca()
    
    ca_cert_path = tmp_path / "ca.crt"
    ca_key_path = tmp_path / "ca.key"
    
    ca_cert_path.write_bytes(ca_cert_bytes)
    ca_key_path.write_bytes(ca_key_bytes)
    
    # Generate an expiring cert (15 days left)
    expiring_cert_bytes, expiring_key_bytes = generate_cert(ca_cert_bytes, ca_key_bytes, days_valid=15)
    expiring_cert_path = tmp_path / "expiring.crt"
    expiring_key_path = tmp_path / "expiring.key"
    expiring_cert_path.write_bytes(expiring_cert_bytes)
    expiring_key_path.write_bytes(expiring_key_bytes)
    
    # Generate a valid cert (60 days left)
    valid_cert_bytes, valid_key_bytes = generate_cert(ca_cert_bytes, ca_key_bytes, days_valid=60)
    valid_cert_path = tmp_path / "valid.crt"
    valid_key_path = tmp_path / "valid.key"
    valid_cert_path.write_bytes(valid_cert_bytes)
    valid_key_path.write_bytes(valid_key_bytes)
    
    return {
        "ca_cert": str(ca_cert_path),
        "ca_key": str(ca_key_path),
        "expiring_cert": str(expiring_cert_path),
        "expiring_key": str(expiring_key_path),
        "valid_cert": str(valid_cert_path),
        "valid_key": str(valid_key_path),
        "dir": tmp_path
    }

def test_check_needs_renewal(temp_env):
    # Threshold 30 days
    assert check_needs_renewal(temp_env["expiring_cert"], 30) is True
    assert check_needs_renewal(temp_env["valid_cert"], 30) is False
    # Check threshold behavior
    assert check_needs_renewal(temp_env["expiring_cert"], 10) is False

def test_renewal_logic(temp_env):
    old_mtime_cert = os.path.getmtime(temp_env["expiring_cert"])
    old_mtime_key = os.path.getmtime(temp_env["expiring_key"])
    
    # Read the old cert to get the previous SAN
    with open(temp_env["expiring_cert"], "rb") as f:
        old_cert = x509.load_pem_x509_certificate(f.read(), default_backend())
    old_san = old_cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value

    renew_certificate(
        temp_env["expiring_cert"], 
        temp_env["expiring_key"], 
        temp_env["ca_cert"], 
        temp_env["ca_key"], 
        dry_run=False
    )
    
    new_mtime_cert = os.path.getmtime(temp_env["expiring_cert"])
    new_mtime_key = os.path.getmtime(temp_env["expiring_key"])
    
    # Assert files were modified
    assert new_mtime_cert != old_mtime_cert
    assert new_mtime_key != old_mtime_key
    
    # Load new cert and verify SANs are identical
    with open(temp_env["expiring_cert"], "rb") as f:
        new_cert = x509.load_pem_x509_certificate(f.read(), default_backend())
    
    new_san = new_cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
    assert new_san == old_san

def test_dry_run_mode(temp_env):
    old_mtime_cert = os.path.getmtime(temp_env["expiring_cert"])
    
    renew_certificate(
        temp_env["expiring_cert"], 
        temp_env["expiring_key"], 
        temp_env["ca_cert"], 
        temp_env["ca_key"], 
        dry_run=True
    )
    
    new_mtime_cert = os.path.getmtime(temp_env["expiring_cert"])
    
    # Assert file was NOT modified
    assert new_mtime_cert == old_mtime_cert
