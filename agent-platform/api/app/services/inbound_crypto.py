"""Fail-closed encryption and keyed fingerprints for inbound provider data."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class InboundCryptoError(RuntimeError):
    """Inbound payload protection or verification failed."""


@dataclass(frozen=True, slots=True)
class ProtectedInboundPayload:
    ciphertext: str
    integrity_hash: str


class InboundPayloadCrypto:
    """Protect payloads with the PII keys, never the credential master key."""

    def protect(self, payload: dict[str, Any]) -> ProtectedInboundPayload:
        canonical = self._canonical(payload)
        return ProtectedInboundPayload(
            ciphertext=self._fernet().encrypt(canonical).decode("ascii"),
            integrity_hash=self._digest("payload-integrity", canonical),
        )

    def reveal(self, *, ciphertext: str, integrity_hash: str) -> dict[str, Any]:
        try:
            canonical = self._fernet().decrypt(ciphertext.encode("ascii"))
        except (InvalidToken, TypeError, ValueError) as exc:
            raise InboundCryptoError("inbound payload could not be decrypted") from exc
        expected = self._digest("payload-integrity", canonical)
        if not hmac.compare_digest(expected, integrity_hash):
            raise InboundCryptoError("inbound payload integrity check failed")
        try:
            value = json.loads(canonical)
        except (UnicodeDecodeError, ValueError) as exc:
            raise InboundCryptoError("inbound payload is not valid JSON") from exc
        if not isinstance(value, dict):
            raise InboundCryptoError("inbound payload must be a JSON object")
        return value

    def thread_key(self, *, channel: str, route_id: str, thread_id: str) -> str:
        material = f"{channel}\0{route_id}\0{thread_id}".encode("utf-8")
        return self._digest("thread-fifo", material)

    @staticmethod
    def _canonical(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def _fernet(self) -> Fernet:
        key = self._read_key(settings.contact_encryption_key_file)
        try:
            return Fernet(key)
        except (TypeError, ValueError) as exc:
            raise InboundCryptoError("contact encryption key is invalid") from exc

    def _digest(self, namespace: str, payload: bytes) -> str:
        key = self._read_key(settings.contact_lookup_hmac_key_file)
        encryption_key = self._read_key(settings.contact_encryption_key_file)
        if len(key) < 32:
            raise InboundCryptoError("contact lookup HMAC key is too short")
        if hmac.compare_digest(key, encryption_key):
            raise InboundCryptoError("inbound encryption and HMAC keys must differ")
        material = namespace.encode("ascii") + b"\0" + payload
        return hmac.new(key, material, hashlib.sha256).hexdigest()

    @staticmethod
    def _read_key(path_value: str) -> bytes:
        try:
            key = Path(path_value).read_bytes().strip()
        except OSError as exc:
            raise InboundCryptoError("inbound data key is unavailable") from exc
        if not key:
            raise InboundCryptoError("inbound data key is empty")
        return key


inbound_payload_crypto = InboundPayloadCrypto()
