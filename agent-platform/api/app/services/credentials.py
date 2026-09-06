"""Encryption boundary for panel-managed integration credentials."""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CredentialStoreUnavailable(RuntimeError):
    pass


class CredentialDecryptError(RuntimeError):
    pass


class CredentialCipher:
    def _fernet(self) -> Fernet:
        path = Path(settings.credential_encryption_key_file)
        try:
            key = path.read_bytes().strip()
        except OSError as exc:
            raise CredentialStoreUnavailable(
                "credential encryption key is unavailable"
            ) from exc
        try:
            return Fernet(key)
        except (ValueError, TypeError) as exc:
            raise CredentialStoreUnavailable(
                "credential encryption key is invalid"
            ) from exc

    def encrypt(self, credentials: dict[str, str]) -> str:
        clean = {
            str(key): str(value)
            for key, value in credentials.items()
            if value is not None
        }
        payload = json.dumps(clean, separators=(",", ":"), sort_keys=True).encode()
        return self._fernet().encrypt(payload).decode()

    def decrypt(self, token: str | None) -> dict[str, str]:
        if not token:
            return {}
        try:
            payload = self._fernet().decrypt(token.encode())
            decoded = json.loads(payload)
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CredentialDecryptError(
                "integration credentials cannot be decrypted"
            ) from exc
        if not isinstance(decoded, dict):
            raise CredentialDecryptError(
                "integration credentials have an invalid shape"
            )
        return {str(key): str(value) for key, value in decoded.items()}


credential_cipher = CredentialCipher()
