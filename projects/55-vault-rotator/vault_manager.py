import argparse
import json
import os
import sys
import secrets
from typing import Any, Dict, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64

# Configuration
SALT_SIZE = 16
NONCE_SIZE = 12
KDF_ITERATIONS = 600_000
KEY_SIZE = 32

class InvalidVaultError(Exception):
    pass

class AuthenticationError(Exception):
    pass


class VaultManager:
    """Cryptographic Engine utilizing AES-256-GCM and PBKDF2HMAC."""

    def __init__(self, vault_path: str, master_password: str):
        self.vault_path = vault_path
        self._master_password = master_password.encode("utf-8")
        self._vault_data: Dict[str, Any] = {}
        self._salt: Optional[bytes] = None

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_SIZE,
            salt=salt,
            iterations=KDF_ITERATIONS,
        )
        return kdf.derive(self._master_password)

    def init_vault(self) -> None:
        """Initializes a new vault with a random salt."""
        self._salt = secrets.token_bytes(SALT_SIZE)
        self._vault_data = {}
        self.save_vault()

    def load_vault(self) -> None:
        """Loads and decrypts the vault."""
        if not os.path.exists(self.vault_path):
            raise FileNotFoundError(f"Vault file not found: {self.vault_path}")

        try:
            with open(self.vault_path, "rb") as f:
                data = json.loads(f.read().decode("utf-8"))
        except json.JSONDecodeError:
            raise InvalidVaultError("Invalid JSON format in vault file.")

        if "salt" not in data or "encrypted_data" not in data:
            raise InvalidVaultError("Missing salt or encrypted_data in vault.")

        self._salt = base64.b64decode(data["salt"])
        encrypted_data = base64.b64decode(data["encrypted_data"])

        if len(encrypted_data) < NONCE_SIZE:
             raise InvalidVaultError("Encrypted data is too short to contain a nonce.")

        nonce = encrypted_data[:NONCE_SIZE]
        ciphertext = encrypted_data[NONCE_SIZE:]

        key = self._derive_key(self._salt)
        aesgcm = AESGCM(key)

        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            self._vault_data = json.loads(plaintext.decode("utf-8"))
        except Exception:
            # We catch generic exceptions from cryptography to abstract it, but typically it raises an InvalidTag error
            raise AuthenticationError("Invalid password or corrupted vault data (authentication failed).")

    def save_vault(self) -> None:
        """Encrypts and saves the current vault state to disk."""
        if self._salt is None:
            raise ValueError("Vault not initialized (salt is missing).")

        key = self._derive_key(self._salt)
        aesgcm = AESGCM(key)
        nonce = secrets.token_bytes(NONCE_SIZE)

        plaintext = json.dumps(self._vault_data).encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        encrypted_payload = nonce + ciphertext

        output = {
            "salt": base64.b64encode(self._salt).decode("utf-8"),
            "encrypted_data": base64.b64encode(encrypted_payload).decode("utf-8"),
        }

        # Write to temporary file first then rename for atomic write
        temp_path = f"{self.vault_path}.tmp"
        with open(temp_path, "wb") as f:
            f.write(json.dumps(output).encode("utf-8"))
        os.replace(temp_path, self.vault_path)

    def set_secret(self, key: str, value: str) -> None:
        """Sets a secret in the vault."""
        self._vault_data[key] = value

    def get_secret(self, key: str) -> Optional[str]:
        """Gets a secret from the vault."""
        return self._vault_data.get(key)

    def export_env(self) -> str:
        """Exports all secrets as .env key-value pairs."""
        return "\n".join([f"{k}={v}" for k, v in self._vault_data.items()])


class RotatorService:
    """Base class for dynamic rotation handlers with a state machine."""

    def __init__(self, name: str, vault_manager: VaultManager):
        self.name = name
        self.vault = vault_manager

    def check_health(self) -> bool:
        """Performs a health check. Should be overridden."""
        return True

    def generate_new_credential(self) -> str:
        """Generates a new credential. Should be overridden."""
        return secrets.token_urlsafe(32)

    def apply_credential(self, new_cred: str) -> None:
        """Applies the new credential. Should be overridden."""
        pass

    def rollback(self, old_cred: str) -> None:
        """Rolls back to the old credential. Should be overridden."""
        pass

    def rotate(self, credential_key: str) -> bool:
        """Executes the rotation state machine."""
        print(f"[{self.name}] Starting rotation for {credential_key}...")

        # 1. Pre-health check
        if not self.check_health():
            print(f"[{self.name}] Pre-rotation health check failed. Aborting.")
            return False

        old_cred = self.vault.get_secret(credential_key)
        if not old_cred:
             print(f"[{self.name}] Secret {credential_key} not found in vault. Generating new one.")
             old_cred = ""

        new_cred = self.generate_new_credential()

        try:
            # 2. Apply new credential to the external service
            self.apply_credential(new_cred)

            # 3. Save new credential to vault
            self.vault.set_secret(credential_key, new_cred)
            self.vault.save_vault()

            # 4. Post-health check
            if not self.check_health():
                raise Exception("Post-rotation health check failed.")

            print(f"[{self.name}] Rotation successful.")
            return True

        except Exception as e:
            print(f"[{self.name}] Rotation failed: {e}. Initiating rollback...")
            try:
                if old_cred:
                    self.rollback(old_cred)
                    self.vault.set_secret(credential_key, old_cred)
                    self.vault.save_vault()
                    print(f"[{self.name}] Rollback successful.")
                else:
                    print(f"[{self.name}] No previous credential to rollback to.")
            except Exception as rollback_err:
                 print(f"[{self.name}] CRITICAL: Rollback failed: {rollback_err}")
            return False

# Concrete implementations for homelab services
class ImmichRotator(RotatorService):
    def check_health(self) -> bool:
        # Simulate check
        return True

    def apply_credential(self, new_cred: str) -> None:
        # Simulate apply
        pass

    def rollback(self, old_cred: str) -> None:
        # Simulate rollback
        pass

# Registry of rotators
ROTATORS = {
    "immich": ImmichRotator,
    # Add other homelab rotators here (plex, telegram, wireguard, etc.)
}

def get_vault_manager(args) -> VaultManager:
    password = os.environ.get("VAULT_PASSWORD")
    if not password:
        print("Error: VAULT_PASSWORD environment variable is required.")
        sys.exit(1)
    return VaultManager(args.vault_file, password)

def main():
    parser = argparse.ArgumentParser(description="Homelab Secret Vault & Dynamic Credential Rotator")
    parser.add_argument("--vault-file", default="vault.json", help="Path to the encrypted vault file")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    subparsers.add_parser("init", help="Initialize a new vault")

    # set
    set_parser = subparsers.add_parser("set", help="Set a secret")
    set_parser.add_argument("key", help="Secret key")
    set_parser.add_argument("value", help="Secret value")

    # get
    get_parser = subparsers.add_parser("get", help="Get a secret")
    get_parser.add_argument("key", help="Secret key")

    # rotate
    rotate_parser = subparsers.add_parser("rotate", help="Rotate a service credential")
    rotate_parser.add_argument("service", help="Service name (e.g., immich)")
    rotate_parser.add_argument("--key", required=True, help="Secret key to rotate (e.g., IMMICH_API_KEY)")

    # export-env
    subparsers.add_parser("export-env", help="Export all secrets in .env format")

    args = parser.parse_args()

    try:
        vm = get_vault_manager(args)

        if args.command == "init":
            vm.init_vault()
            if args.json:
                print(json.dumps({"status": "success", "message": "Vault initialized"}))
            else:
                print("Vault initialized successfully.")

        elif args.command == "set":
            vm.load_vault()
            vm.set_secret(args.key, args.value)
            vm.save_vault()
            if args.json:
                print(json.dumps({"status": "success", "key": args.key}))
            else:
                print(f"Secret '{args.key}' set successfully.")

        elif args.command == "get":
            vm.load_vault()
            value = vm.get_secret(args.key)
            if value is None:
                if args.json:
                    print(json.dumps({"status": "error", "message": "Secret not found"}))
                else:
                    print(f"Secret '{args.key}' not found.")
                sys.exit(1)
            else:
                if args.json:
                    print(json.dumps({"status": "success", "key": args.key, "value": value}))
                else:
                    print(value)

        elif args.command == "rotate":
            vm.load_vault()
            service_class = ROTATORS.get(args.service.lower())
            if not service_class:
                print(f"Error: Unknown service '{args.service}'")
                sys.exit(1)

            rotator = service_class(args.service, vm)
            success = rotator.rotate(args.key)
            if not success:
                sys.exit(1)

        elif args.command == "export-env":
            vm.load_vault()
            env_data = vm.export_env()
            print(env_data)

    except Exception as e:
        if args.json:
             print(json.dumps({"status": "error", "message": str(e)}))
        else:
             print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
