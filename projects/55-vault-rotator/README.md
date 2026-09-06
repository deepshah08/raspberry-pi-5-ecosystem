# Project 55: Homelab Secret Vault & Dynamic Credential Rotator

This project provides a centralized, encrypted credential store and automated secret rotation daemon across homelab services (such as Immich API keys, Plex tokens, Telegram bot tokens, WireGuard preshared keys).

## Architecture

The system utilizes AES-256-GCM for authenticated encryption and PBKDF2HMAC (SHA-256) for key derivation. Secrets are dynamically loaded into memory or `tmpfs`, ensuring zero host disk writes.

```mermaid
sequenceDiagram
    participant CLI as Vault CLI / Cron
    participant Vault as VaultManager
    participant Rotator as ServiceRotator
    participant Service as Homelab Service

    CLI->>Rotator: rotate(service, key)
    Rotator->>Service: Pre-rotation Health Check
    alt Health Check Failed
        Service-->>Rotator: Error
        Rotator-->>CLI: Abort Rotation
    else Health Check Passed
        Rotator->>Vault: get_secret(key)
        Vault-->>Rotator: Old Credential
        Rotator->>Rotator: Generate New Credential
        Rotator->>Service: apply_credential(New Credential)
        Rotator->>Vault: set_secret(key, New Credential)
        Rotator->>Service: Post-rotation Health Check
        alt Post Check Passed
            Service-->>Rotator: OK
            Rotator->>Vault: save_vault()
            Rotator-->>CLI: Rotation Successful
        else Post Check Failed
            Service-->>Rotator: Error
            Rotator->>Rotator: rollback(Old Credential)
            Rotator->>Service: apply_credential(Old Credential)
            Rotator->>Vault: set_secret(key, Old Credential)
            Rotator->>Vault: save_vault()
            Rotator-->>CLI: Rotation Failed - Rolled Back
        end
    end
```

## Key Derivation Specification

- **Algorithm**: PBKDF2HMAC
- **Hash**: SHA-256
- **Salt**: 16 bytes (randomly generated during `init`)
- **Iterations**: 600,000
- **Key Size**: 32 bytes
- **Cipher**: AES-256-GCM (12 byte nonce, 16 byte auth tag)

## Disaster Recovery / Recovery Key Procedure

In the event of lost access to the running environment or failure of homelab services:
1. Obtain the `vault.json` file securely from backups.
2. Ensure you have the `VAULT_PASSWORD` (Master Password).
3. Set the environment variable: `export VAULT_PASSWORD="your-master-password"`.
4. Run the export command to extract all credentials to `.env` format:
   `python vault_manager.py export-env > recovered.env`
5. Note: This will export plaintext credentials to disk. Ensure the `recovered.env` file is stored securely or within a `tmpfs` mount if required by security policies.
