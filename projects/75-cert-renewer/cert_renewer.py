import argparse
import datetime
import os
import sys
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

def check_needs_renewal(cert_path: str, days: int) -> bool:
    """Check if the certificate at cert_path needs renewal."""
    if not os.path.exists(cert_path):
        return True # If it doesn't exist, we probably need to create it

    with open(cert_path, "rb") as f:
        cert_data = f.read()

    cert = x509.load_pem_x509_certificate(cert_data, default_backend())
    
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    not_valid_after = cert.not_valid_after_utc.replace(tzinfo=None)
    
    delta = not_valid_after - now
    if delta.days <= days:
        return True
        
    return False

def sync_to_vault(cert_path: str, key_path: str, new_cert_bytes: bytes, new_key_bytes: bytes, dry_run: bool):
    """Saves the generated certificate and key to the filesystem."""
    if dry_run:
        print(f"[DRY RUN] Would write new cert to {cert_path}")
        print(f"[DRY RUN] Would write new key to {key_path}")
        return

    # Ensure directories exist
    os.makedirs(os.path.dirname(cert_path), exist_ok=True)
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    
    with open(cert_path, "wb") as f:
        f.write(new_cert_bytes)
        
    with open(key_path, "wb") as f:
        f.write(new_key_bytes)
        
    print(f"Successfully renewed and saved certificate to {cert_path} and key to {key_path}")


def renew_certificate(cert_path: str, key_path: str, ca_cert_path: str, ca_key_path: str, dry_run: bool):
    """Renews the certificate while preserving Subject and SANs."""
    # 1. Load the old cert
    with open(cert_path, "rb") as f:
        cert_data = f.read()
    old_cert = x509.load_pem_x509_certificate(cert_data, default_backend())
    
    # Extract Subject
    subject = old_cert.subject
    
    # Extract SANs
    try:
        san_ext = old_cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        sans = san_ext.value
    except x509.ExtensionNotFound:
        sans = None
        
    # 2. Load CA
    with open(ca_cert_path, "rb") as f:
        ca_cert_data = f.read()
    ca_cert = x509.load_pem_x509_certificate(ca_cert_data, default_backend())
    
    with open(ca_key_path, "rb") as f:
        ca_key_data = f.read()
    ca_key = serialization.load_pem_private_key(ca_key_data, password=None, backend=default_backend())
    
    # 3. Generate New Keypair
    new_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # 4. Generate CSR
    builder = x509.CertificateBuilder()
    builder = builder.subject_name(subject)
    builder = builder.issuer_name(ca_cert.subject)
    builder = builder.public_key(new_private_key.public_key())
    builder = builder.serial_number(x509.random_serial_number())
    builder = builder.not_valid_before(datetime.datetime.now(datetime.timezone.utc))
    builder = builder.not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
    
    if sans:
        builder = builder.add_extension(sans, critical=False)
        
    # 5. Sign the Certificate
    new_cert = builder.sign(
        private_key=ca_key,
        algorithm=hashes.SHA256(),
        backend=default_backend()
    )
    
    # 6. Serialize
    new_cert_bytes = new_cert.public_bytes(serialization.Encoding.PEM)
    new_key_bytes = new_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    # 7. Sync
    sync_to_vault(cert_path, key_path, new_cert_bytes, new_key_bytes, dry_run)


def main():
    parser = argparse.ArgumentParser(description="Automated Homelab SSL/mTLS Certificate Renewer")
    parser.add_argument("--cert-file", type=str, required=True, help="Path to the target certificate file")
    parser.add_argument("--ca-cert", type=str, required=True, help="Path to the CA certificate file")
    parser.add_argument("--ca-key", type=str, required=True, help="Path to the CA private key file")
    parser.add_argument("--days", type=int, default=30, help="Threshold in days to trigger renewal")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without modifying files")
    
    args = parser.parse_args()
    
    # To determine the key path, we'll replace .crt or .pem with .key.
    # In a real app we might want an explicit arg, but we'll assume standard naming here.
    base_name = os.path.splitext(args.cert_file)[0]
    key_file = base_name + ".key"
    
    if check_needs_renewal(args.cert_file, args.days):
        print(f"Certificate {args.cert_file} expires within {args.days} days (or is missing). Renewing...")
        if not os.path.exists(args.cert_file) and args.dry_run:
            print("[DRY RUN] Cannot renew a missing certificate because we need it to copy Subject/SANs.")
            print("[DRY RUN] In reality, you'd provide an existing cert, or a generation command.")
            sys.exit(1)
        elif not os.path.exists(args.cert_file):
            print(f"Error: {args.cert_file} does not exist. Initial generation not implemented in this script.")
            sys.exit(1)
            
        renew_certificate(args.cert_file, key_file, args.ca_cert, args.ca_key, args.dry_run)
    else:
        print(f"Certificate {args.cert_file} is valid for more than {args.days} days.")

if __name__ == "__main__":
    main()
