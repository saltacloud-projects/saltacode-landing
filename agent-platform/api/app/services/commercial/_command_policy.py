"""Shared normalization and integrity policy for commercial commands."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import Enum

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class CommercialCommandPolicy:
    """Normalize commands while preserving each domain service's error contract."""

    def __init__(
        self,
        *,
        validation_error: type[Exception],
        idempotency_error: type[Exception],
    ) -> None:
        self._validation_error = validation_error
        self._idempotency_error = idempotency_error

    def required_text(self, value: str, field: str, max_length: int) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > max_length:
            raise self._validation_error(f"invalid {field}")
        return normalized

    def optional_text(self, value: str | None, max_length: int) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > max_length:
            raise self._validation_error("optional text is too long")
        return normalized or None

    def aware_utc(self, value: datetime, field: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise self._validation_error(f"{field} must include a timezone")
        return value.astimezone(UTC)

    def enum_value(self, enum_type: type[Enum], value, field: str):
        try:
            return enum_type(value)
        except (TypeError, ValueError) as exc:
            raise self._validation_error(f"invalid {field}") from exc

    @staticmethod
    def command_hash(payload: dict) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def assert_hash(self, actual: str, expected: str) -> None:
        if not _SHA256_HEX.fullmatch(actual) or actual != expected:
            raise self._idempotency_error(
                "idempotency key belongs to another commercial command"
            )
