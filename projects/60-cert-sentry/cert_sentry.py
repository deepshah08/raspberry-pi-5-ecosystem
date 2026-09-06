import argparse
import datetime
import logging
import os
import socket
import ssl
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Fallback path if not configured
ALERTS_ROUTER_PATH = os.path.join(os.path.dirname(__file__), "..", "56-notification-engine")
if os.path.exists(ALERTS_ROUTER_PATH):
    sys.path.insert(0, os.path.abspath(ALERTS_ROUTER_PATH))
    try:
        from router import AlertRouter, Severity
    except ImportError:
        AlertRouter = None
        Severity = None
else:
    AlertRouter = None
    Severity = None


class CertManager:
    def __init__(self, output_dir: str = "/certs"):
        self.output_dir = Path(output_dir)
        self.ca_key_path = self.output_dir / "ca.key"
        self.ca_cert_path = self.output_dir / "ca.crt"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _save_file(self, path: Path, data: bytes, permissions: int):
        with open(path, "wb") as f:
            f.write(data)
        os.chmod(path, permissions)

    def generate_ca(self):
        if self.ca_key_path.exists() and self.ca_cert_path.exists():
            logger.info("CA already exists. Skipping generation.")
            return

        logger.info("Generating new Root CA...")
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Homelab Cert Sentry"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"Homelab Root CA"),
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
        ).sign(private_key, hashes.SHA256())

        self._save_file(
            self.ca_key_path,
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            0o600
        )
        self._save_file(
            self.ca_cert_path,
            cert.public_bytes(serialization.Encoding.PEM),
            0o644
        )
        logger.info("Root CA generated successfully.")

    def issue_cert(self, domain: str, days_valid: int = 397) -> bool:
        if not self.ca_key_path.exists() or not self.ca_cert_path.exists():
            logger.error("Root CA not found. Please generate CA first.")
            return False

        logger.info(f"Issuing certificate for {domain}...")

        with open(self.ca_key_path, "rb") as f:
            ca_private_key = serialization.load_pem_private_key(f.read(), password=None)
        with open(self.ca_cert_path, "rb") as f:
            ca_cert = x509.load_pem_x509_certificate(f.read())

        server_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        subject = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Homelab Server"),
            x509.NameAttribute(NameOID.COMMON_NAME, domain),
        ])

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            ca_cert.subject
        ).public_key(
            server_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.now(datetime.timezone.utc)
        ).not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_valid)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(domain)]), critical=False,
        ).sign(ca_private_key, hashes.SHA256())

        key_path = self.output_dir / f"{domain}.key"
        cert_path = self.output_dir / f"{domain}.crt"

        self._save_file(
            key_path,
            server_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            0o600
        )
        self._save_file(
            cert_path,
            cert.public_bytes(serialization.Encoding.PEM),
            0o644
        )
        logger.info(f"Certificate for {domain} issued successfully.")
        return True


class TLSProbe:
    @staticmethod
    def get_expiry(host: str, port: int = 443, timeout: int = 5) -> Optional[datetime.datetime]:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert_bin = ssock.getpeercert(binary_form=True)
                    if cert_bin is None:
                        return None
                    cert = x509.load_der_x509_certificate(cert_bin)
                    return cert.not_valid_after_utc
        except Exception as e:
            logger.error(f"Failed to probe {host}:{port}: {e}")
            return None


class Sentinel:
    def __init__(self, cert_manager: CertManager, threshold_days: int = 14, dry_run: bool = False):
        self.cert_manager = cert_manager
        self.threshold_days = threshold_days
        self.dry_run = dry_run
        self.router = AlertRouter() if AlertRouter else None

    def _notify(self, title: str, body: str, severity):
        if self.router and not self.dry_run:
            self.router.dispatch("CertSentry", title, body, severity)
        else:
            logger.info(f"[Notify (Dry Run)] {severity.value if severity else 'INFO'} - {title}: {body}")

    def check_local_file(self, domain: str, cert_path: Path) -> Optional[int]:
        if not cert_path.exists():
            return None
        try:
            with open(cert_path, "rb") as f:
                cert = x509.load_pem_x509_certificate(f.read())
                expiry = cert.not_valid_after_utc
                return (expiry - datetime.datetime.now(datetime.timezone.utc)).days
        except Exception as e:
            logger.error(f"Failed to read local cert {cert_path}: {e}")
            return None

    def renew_cert(self, domain: str):
        if self.dry_run:
            logger.info(f"[Dry Run] Would renew certificate for {domain}")
            return
        logger.info(f"Triggering automated renewal for {domain}")
        success = self.cert_manager.issue_cert(domain)
        if success and Severity:
            self._notify("Cert Renewed", f"Successfully renewed certificate for {domain}", Severity.INFO)
        elif not success and Severity:
            self._notify("Cert Renewal Failed", f"Failed to renew certificate for {domain}", Severity.WARNING)

    def check_endpoint(self, host: str, port: int = 443):
        logger.info(f"Checking expiry for {host}:{port}...")
        expiry = TLSProbe.get_expiry(host, port)

        if not expiry:
            msg = f"Could not determine expiry for {host}:{port}."
            logger.error(msg)
            if Severity:
                self._notify("Cert Probe Failed", msg, Severity.WARNING)
            return

        remaining = (expiry - datetime.datetime.now(datetime.timezone.utc)).days
        logger.info(f"Certificate for {host}:{port} expires in {remaining} days (Threshold: {self.threshold_days}).")

        if remaining <= self.threshold_days:
            msg = f"Certificate for {host}:{port} expires in {remaining} days!"
            logger.warning(msg)
            if Severity:
                self._notify("Cert Expiry Warning", msg, Severity.WARNING)

            # Extract domain from host if it's a domain name (simple heuristic)
            if host.endswith(".home"):
                self.renew_cert(host)
            else:
                logger.info(f"Cannot auto-renew for IP or non-local domain {host}")
        else:
            logger.info(f"Certificate for {host}:{port} is healthy.")

    def scan_local_certs(self):
        logger.info(f"Scanning local certificates in {self.cert_manager.output_dir}...")
        for cert_file in self.cert_manager.output_dir.glob("*.crt"):
            if cert_file.name == "ca.crt":
                continue

            domain = cert_file.name.replace(".crt", "")
            remaining = self.check_local_file(domain, cert_file)

            if remaining is not None:
                logger.info(f"Local certificate for {domain} expires in {remaining} days.")
                if remaining <= self.threshold_days:
                    msg = f"Local certificate for {domain} expires in {remaining} days!"
                    logger.warning(msg)
                    if Severity:
                        self._notify("Local Cert Expiry Warning", msg, Severity.WARNING)
                    self.renew_cert(domain)

    def run_loop(self, endpoints: list[Tuple[str, int]], interval: int = 86400):
        logger.info(f"Starting Sentinel loop with {interval}s interval...")
        while True:
            self.scan_local_certs()
            for host, port in endpoints:
                self.check_endpoint(host, port)
            logger.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Internal TLS Certificate Authority & Expiry Sentinel")
    parser.add_argument("--generate-ca", action="store_true", help="Generate Root CA if it doesn't exist")
    parser.add_argument("--issue-cert", type=str, help="Issue certificate for a given domain")
    parser.add_argument("--check-expiry", type=str, help="Check TLS expiry of a host:port (e.g. 192.168.1.80:443)")
    parser.add_argument("--run-loop", action="store_true", help="Run the continuous sentinel loop")
    parser.add_argument("--interval", type=int, default=86400, help="Interval in seconds for the sentinel loop (default: 86400)")
    parser.add_argument("--endpoints", type=str, nargs="*", default=[], help="List of host:port to check in the loop")
    parser.add_argument("--threshold-days", type=int, default=14, help="Days before expiry to trigger renewal/alert")
    parser.add_argument("--dry-run", action="store_true", help="Do not send notifications or execute renewals")
    parser.add_argument("--output-dir", type=str, default="/certs", help="Directory to store certificates")

    args = parser.parse_args()

    manager = CertManager(output_dir=args.output_dir)
    sentinel = Sentinel(manager, threshold_days=args.threshold_days, dry_run=args.dry_run)

    if args.generate_ca:
        manager.generate_ca()

    if args.issue_cert:
        manager.issue_cert(args.issue_cert)

    if args.check_expiry:
        try:
            host, port_str = args.check_expiry.split(":")
            port = int(port_str)
            sentinel.check_endpoint(host, port)
        except ValueError:
            logger.error("Invalid format for --check-expiry. Use host:port")
            sys.exit(1)

    if args.run_loop:
        endpoints = []
        for ep in args.endpoints:
            try:
                h, p = ep.split(":")
                endpoints.append((h, int(p)))
            except ValueError:
                logger.error(f"Invalid format for endpoint {ep}. Use host:port")
                sys.exit(1)
        sentinel.run_loop(endpoints, interval=args.interval)


if __name__ == "__main__":
    main()
