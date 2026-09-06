import json
import os
import sys
from pathlib import Path
import pytest
import base64
from unittest.mock import patch, MagicMock

# Fix sys.path to allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vault_manager import VaultManager, RotatorService, AuthenticationError, InvalidVaultError, main

@pytest.fixture
def temp_vault_file(tmp_path):
    return str(tmp_path / "test_vault.json")

def test_encryption_decryption_roundtrip(temp_vault_file):
    password = "super-secret-master-password"

    # Initialize and save
    vm1 = VaultManager(temp_vault_file, password)
    vm1.init_vault()
    vm1.set_secret("API_KEY", "12345")
    vm1.save_vault()

    # Load and verify
    vm2 = VaultManager(temp_vault_file, password)
    vm2.load_vault()
    assert vm2.get_secret("API_KEY") == "12345"

def test_tamper_detection(temp_vault_file):
    password = "super-secret-master-password"

    vm = VaultManager(temp_vault_file, password)
    vm.init_vault()
    vm.set_secret("API_KEY", "12345")
    vm.save_vault()

    # Tamper with the encrypted data
    with open(temp_vault_file, "r") as f:
        data = json.load(f)

    encrypted_data = base64.b64decode(data["encrypted_data"])
    # Modify the last byte (auth tag)
    tampered_data = encrypted_data[:-1] + bytes([encrypted_data[-1] ^ 1])
    data["encrypted_data"] = base64.b64encode(tampered_data).decode("utf-8")

    with open(temp_vault_file, "w") as f:
        json.dump(data, f)

    vm_tampered = VaultManager(temp_vault_file, password)
    with pytest.raises(AuthenticationError):
        vm_tampered.load_vault()

def test_export_env(temp_vault_file):
    password = "pw"
    vm = VaultManager(temp_vault_file, password)
    vm.init_vault()
    vm.set_secret("K1", "V1")
    vm.set_secret("K2", "V2")

    env_output = vm.export_env()
    assert "K1=V1" in env_output
    assert "K2=V2" in env_output

class MockSuccessRotator(RotatorService):
    def check_health(self):
        return True

    def generate_new_credential(self):
         return "new-cred"

    def apply_credential(self, new_cred):
        pass

    def rollback(self, old_cred):
        pass

class MockFailureRotator(RotatorService):
    def __init__(self, name, vm):
        super().__init__(name, vm)
        self.health_checks = 0
        self.rolled_back = False

    def check_health(self):
        # Pass first check, fail second check
        self.health_checks += 1
        return self.health_checks == 1

    def generate_new_credential(self):
         return "new-cred"

    def apply_credential(self, new_cred):
        pass

    def rollback(self, old_cred):
        self.rolled_back = True

def test_rotation_success(temp_vault_file):
    vm = VaultManager(temp_vault_file, "pw")
    vm.init_vault()
    vm.set_secret("MY_KEY", "old-cred")
    vm.save_vault()

    rotator = MockSuccessRotator("mock", vm)
    success = rotator.rotate("MY_KEY")

    assert success is True
    assert vm.get_secret("MY_KEY") == "new-cred"

def test_rotation_failure_and_rollback(temp_vault_file):
    vm = VaultManager(temp_vault_file, "pw")
    vm.init_vault()
    vm.set_secret("MY_KEY", "old-cred")
    vm.save_vault()

    rotator = MockFailureRotator("mock", vm)
    success = rotator.rotate("MY_KEY")

    assert success is False
    assert rotator.rolled_back is True
    # Verify rollback was applied to vault
    assert vm.get_secret("MY_KEY") == "old-cred"

@patch('sys.argv', ['vaultctl', '--vault-file', 'dummy.json', 'init'])
@patch('os.environ', {'VAULT_PASSWORD': 'pw'})
@patch('vault_manager.VaultManager')
def test_cli_init(mock_vm_class):
    mock_vm = MagicMock()
    mock_vm_class.return_value = mock_vm

    main()
    mock_vm.init_vault.assert_called_once()

@patch('sys.argv', ['vaultctl', '--vault-file', 'dummy.json', 'set', 'K1', 'V1'])
@patch('os.environ', {'VAULT_PASSWORD': 'pw'})
@patch('vault_manager.VaultManager')
def test_cli_set(mock_vm_class):
    mock_vm = MagicMock()
    mock_vm_class.return_value = mock_vm

    main()
    mock_vm.load_vault.assert_called_once()
    mock_vm.set_secret.assert_called_with('K1', 'V1')
    mock_vm.save_vault.assert_called_once()
