"""Signed, server-owned browser conversation identity."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class SessionResolution:
    session_id: UUID
    cookie_value: str
    is_new: bool


class SignedSessionManager:
    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("session signing secret must contain at least 32 characters")
        self._secret = secret.encode("utf-8")

    def resolve(self, cookie_value: str | None) -> SessionResolution:
        existing = self.existing(cookie_value)
        if existing is not None:
            return existing
        session_id = uuid4()
        return SessionResolution(session_id, self._encode(session_id), True)

    def existing(self, cookie_value: str | None) -> SessionResolution | None:
        """Validate an existing session without allocating a replacement identity."""
        if cookie_value:
            parsed = self._verify(cookie_value)
            if parsed is not None:
                return SessionResolution(parsed, cookie_value, False)
        return None

    def _encode(self, session_id: UUID) -> str:
        value = str(session_id)
        signature = hmac.new(self._secret, value.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{value}.{signature}"

    def _verify(self, cookie_value: str) -> UUID | None:
        try:
            value, supplied_signature = cookie_value.split(".", 1)
            session_id = UUID(value)
        except (ValueError, AttributeError):
            return None
        if not supplied_signature.isascii():
            return None
        expected = hmac.new(
            self._secret, str(session_id).encode("ascii"), hashlib.sha256
        ).hexdigest()
        return session_id if hmac.compare_digest(expected, supplied_signature) else None
