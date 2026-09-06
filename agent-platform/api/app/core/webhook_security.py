"""Signature verification for channel webhooks."""

from __future__ import annotations

import hashlib
import hmac


class InvalidWebhookSignature(ValueError):
    """Raised when a provider signature is missing or invalid."""


def verify_meta_signature(
    *, raw_body: bytes, signature_header: str | None, app_secret: str
) -> None:
    """Validate Meta's ``X-Hub-Signature-256`` over the exact request bytes."""
    if not app_secret:
        raise InvalidWebhookSignature(
            "webhook signature verification is not configured"
        )
    if not signature_header or not signature_header.startswith("sha256="):
        raise InvalidWebhookSignature("webhook signature is missing")
    supplied = signature_header.removeprefix("sha256=").strip().lower()
    if len(supplied) != 64:
        raise InvalidWebhookSignature("webhook signature is malformed")
    expected = hmac.new(
        app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise InvalidWebhookSignature("webhook signature is invalid")
