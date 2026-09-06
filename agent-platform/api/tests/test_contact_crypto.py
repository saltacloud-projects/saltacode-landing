"""Unit coverage for contact-data protection primitives."""

import pytest
from cryptography.fernet import Fernet

from app.services.commercial.contact_crypto import (
    ContactCrypto,
    ContactCryptoUnavailable,
    InvalidContactPointValue,
)


@pytest.fixture
def crypto(monkeypatch, tmp_path) -> ContactCrypto:
    encryption_key = tmp_path / "contact-data.key"
    lookup_key = tmp_path / "contact-lookup.key"
    encryption_key.write_bytes(Fernet.generate_key())
    lookup_key.write_bytes(b"lookup-key-with-at-least-thirty-two-bytes")
    monkeypatch.setattr(
        "app.services.commercial.contact_crypto.settings.contact_encryption_key_file",
        encryption_key,
    )
    monkeypatch.setattr(
        "app.services.commercial.contact_crypto.settings.contact_lookup_hmac_key_file",
        lookup_key,
    )
    return ContactCrypto()


def test_contact_values_are_encrypted_masked_and_keyed(crypto: ContactCrypto) -> None:
    raw_value = "Oscar.Vargas@example.com"

    first = crypto.protect(kind="email", value=raw_value)
    second = crypto.protect(kind="email", value=raw_value.casefold())

    assert raw_value.casefold() not in first.ciphertext.casefold()
    assert "oscar.vargas" not in first.masked_value
    assert first.ciphertext != second.ciphertext
    assert first.lookup_hmac == second.lookup_hmac
    assert crypto.decrypt(first.ciphertext) == raw_value.casefold()


def test_phone_requires_explicit_country_code(crypto: ContactCrypto) -> None:
    protected = crypto.protect(kind="phone", value="+54 9 387 123-4567")

    assert crypto.decrypt(protected.ciphertext) == "+5493871234567"
    assert protected.masked_value.endswith("4567")
    with pytest.raises(InvalidContactPointValue):
        crypto.protect(kind="phone", value="3871234567")


def test_contact_crypto_fails_closed_when_key_material_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "app.services.commercial.contact_crypto.settings.contact_encryption_key_file",
        tmp_path / "missing.key",
    )

    with pytest.raises(ContactCryptoUnavailable):
        ContactCrypto().protect(kind="email", value="test@example.com")


def test_contact_crypto_rejects_reused_encryption_and_lookup_keys(
    monkeypatch,
    tmp_path,
) -> None:
    shared_key = tmp_path / "shared.key"
    shared_key.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(
        "app.services.commercial.contact_crypto.settings.contact_encryption_key_file",
        shared_key,
    )
    monkeypatch.setattr(
        "app.services.commercial.contact_crypto.settings.contact_lookup_hmac_key_file",
        shared_key,
    )

    with pytest.raises(ContactCryptoUnavailable):
        ContactCrypto().protect(kind="email", value="test@example.com")
