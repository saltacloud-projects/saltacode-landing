from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.models.integration_source import IntegrationSource
from app.schemas.integrations import IntegrationSourceOut
from app.services.credentials import CredentialCipher, CredentialDecryptError


def test_credentials_are_encrypted_and_round_trip(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "source.key"
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(
        "app.services.credentials.settings.credential_encryption_key_file", key_file
    )
    cipher = CredentialCipher()

    encrypted = cipher.encrypt({"token": "top-secret", "tenant": "example"})

    assert "top-secret" not in encrypted
    assert cipher.decrypt(encrypted) == {
        "tenant": "example",
        "token": "top-secret",
    }


def test_credentials_fail_closed_with_a_different_key(monkeypatch, tmp_path) -> None:
    key_file = tmp_path / "source.key"
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(
        "app.services.credentials.settings.credential_encryption_key_file", key_file
    )
    encrypted = CredentialCipher().encrypt({"token": "top-secret"})
    key_file.write_bytes(Fernet.generate_key())

    with pytest.raises(CredentialDecryptError):
        CredentialCipher().decrypt(encrypted)


def test_admin_source_contract_never_serializes_credentials() -> None:
    source = IntegrationSource(
        id=uuid4(),
        name="Example",
        slug="example",
        source_type="http",
        base_url="https://api.example.com",
        allowed_hosts=["api.example.com"],
        auth_type="bearer",
        auth_config={},
        encrypted_credentials="encrypted-value",
        default_headers={},
        is_active=True,
        is_public=False,
        verify_tls=True,
        allow_private_network=False,
        timeout_seconds=30,
        max_response_bytes=4096,
        created_by="test",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    payload = IntegrationSourceOut.from_model(source).model_dump()

    assert payload["has_credentials"] is True
    assert "encrypted_credentials" not in payload
    assert "credentials" not in payload
