"""Fail-closed protection and lookup primitives for contact details."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import EmailStr, TypeAdapter, ValidationError

from app.config import settings

_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_E164_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")


class ContactCryptoError(Exception):
    """Base error for contact-data protection failures."""


class ContactCryptoUnavailable(ContactCryptoError):
    """Required key material is missing or invalid."""


class ContactDecryptError(ContactCryptoError):
    """Stored contact data cannot be decrypted with the active key."""


class InvalidContactPointValue(ContactCryptoError):
    """A contact point cannot be normalized without guessing identity data."""


@dataclass(frozen=True, slots=True)
class ProtectedContactPoint:
    """Safe persistence representation of one normalized contact point."""

    ciphertext: str
    lookup_hmac: str
    masked_value: str


class ContactCrypto:
    """Encrypt contact values and produce deterministic keyed lookup digests."""

    def protect(self, *, kind: str, value: str) -> ProtectedContactPoint:
        normalized = self.normalize(kind=kind, value=value)
        ciphertext = self._fernet().encrypt(normalized.encode("utf-8")).decode("ascii")
        return ProtectedContactPoint(
            ciphertext=ciphertext,
            lookup_hmac=self._digest(normalized),
            masked_value=self._mask(kind=kind, normalized=normalized),
        )

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise ContactDecryptError("contact data could not be decrypted") from exc

    def lookup(self, *, kind: str, value: str) -> str:
        return self._digest(self.normalize(kind=kind, value=value))

    @staticmethod
    def normalize(*, kind: str, value: str) -> str:
        candidate = value.strip()
        if kind == "email":
            try:
                return str(_EMAIL_ADAPTER.validate_python(candidate)).casefold()
            except ValidationError as exc:
                raise InvalidContactPointValue("invalid email contact point") from exc
        if kind == "phone":
            compact = re.sub(r"[\s().-]", "", candidate)
            if not _E164_PATTERN.fullmatch(compact):
                raise InvalidContactPointValue(
                    "phone contact points must use explicit E.164 format"
                )
            return compact
        raise InvalidContactPointValue("unsupported contact point kind")

    def _fernet(self) -> Fernet:
        key = self._read_key(
            settings.contact_encryption_key_file,
            label="contact encryption",
        )
        try:
            return Fernet(key)
        except (TypeError, ValueError) as exc:
            raise ContactCryptoUnavailable("contact encryption key is invalid") from exc

    def _digest(self, normalized: str) -> str:
        key = self._read_key(
            settings.contact_lookup_hmac_key_file,
            label="contact lookup HMAC",
        )
        if len(key) < 32:
            raise ContactCryptoUnavailable(
                "contact lookup HMAC key must contain at least 32 bytes"
            )
        encryption_key = self._read_key(
            settings.contact_encryption_key_file,
            label="contact encryption",
        )
        if hmac.compare_digest(key, encryption_key):
            raise ContactCryptoUnavailable(
                "contact encryption and lookup HMAC keys must be distinct"
            )
        return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _read_key(path_value: str, *, label: str) -> bytes:
        try:
            key = Path(path_value).read_bytes().strip()
        except OSError as exc:
            raise ContactCryptoUnavailable(f"{label} key is unavailable") from exc
        if not key:
            raise ContactCryptoUnavailable(f"{label} key is empty")
        return key

    @staticmethod
    def _mask(*, kind: str, normalized: str) -> str:
        if kind == "phone":
            return (
                f"{normalized[:2]}{'*' * max(len(normalized) - 6, 4)}{normalized[-4:]}"
            )

        local, domain = normalized.rsplit("@", 1)
        domain_name, separator, suffix = domain.partition(".")
        masked_local = f"{local[0]}***" if len(local) > 1 else "***"
        masked_domain = f"{domain_name[0]}***"
        if separator:
            masked_domain = f"{masked_domain}.{suffix}"
        return f"{masked_local}@{masked_domain}"


contact_crypto = ContactCrypto()
