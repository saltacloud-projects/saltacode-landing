import hashlib
import hmac

import pytest

from app.core.webhook_security import InvalidWebhookSignature, verify_meta_signature


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_meta_signature_accepts_exact_request_bytes() -> None:
    body = b'{"entry":[]}'
    verify_meta_signature(
        raw_body=body, signature_header=_signature(body, "secret"), app_secret="secret"
    )


@pytest.mark.parametrize("header", [None, "", "sha1=abc", "sha256=short"])
def test_meta_signature_rejects_missing_or_malformed_header(header: str | None) -> None:
    with pytest.raises(InvalidWebhookSignature):
        verify_meta_signature(
            raw_body=b"{}", signature_header=header, app_secret="secret"
        )


def test_meta_signature_rejects_tampered_body() -> None:
    header = _signature(b'{"safe":true}', "secret")
    with pytest.raises(InvalidWebhookSignature):
        verify_meta_signature(
            raw_body=b'{"safe":false}', signature_header=header, app_secret="secret"
        )
