"""JWT compatibility and admin authentication boundary tests."""

import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.config import settings
from app.core.auth import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.routers.admin.auth import refresh, require_admin
from app.schemas.admin import RefreshRequest


class _UnexpectedDatabase:
    async def execute(self, _statement):
        raise AssertionError("invalid tokens must be rejected before database access")


def test_access_token_preserves_claims_algorithm_and_expiration(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret-" * 4)
    monkeypatch.setattr(settings, "jwt_access_token_expire_minutes", 12)
    user_id = str(uuid4())

    token = create_access_token(user_id, "admin@example.test", "admin")
    header = jwt.get_unverified_header(token)
    payload = decode_token(token)

    assert header["alg"] == ALGORITHM == "HS256"
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["email"] == "admin@example.test"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert payload["jti"]
    assert 11 * 60 <= payload["exp"] - int(time.time()) <= 12 * 60


def test_refresh_token_preserves_claims_and_expiration(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret-" * 4)
    monkeypatch.setattr(settings, "jwt_refresh_token_expire_days", 9)
    user_id = str(uuid4())

    payload = decode_token(create_refresh_token(user_id))

    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"
    assert payload["jti"]
    assert 8 * 86_400 <= payload["exp"] - int(time.time()) <= 9 * 86_400


@pytest.mark.parametrize("kind", ["expired", "wrong-signature", "wrong-algorithm"])
def test_decode_token_rejects_invalid_tokens(monkeypatch, kind):
    secret = "test-secret-" * 4
    monkeypatch.setattr(settings, "jwt_secret_key", secret)
    payload = {
        "sub": str(uuid4()),
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    signing_secret = secret
    algorithm = ALGORITHM
    if kind == "expired":
        payload["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif kind == "wrong-signature":
        signing_secret = "different-secret-" * 4
    else:
        algorithm = "HS384"

    token = jwt.encode(payload, signing_secret, algorithm=algorithm)

    assert decode_token(token) is None


async def test_invalid_access_token_preserves_admin_http_error():
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials="not-a-jwt",
    )

    with pytest.raises(HTTPException) as error:
        await require_admin(credentials, _UnexpectedDatabase())

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Token inválido o expirado"
    assert error.value.headers == {"WWW-Authenticate": "Bearer"}


async def test_invalid_refresh_token_preserves_admin_http_error():
    with pytest.raises(HTTPException) as error:
        await refresh(RefreshRequest(refresh_token="not-a-jwt"), _UnexpectedDatabase())

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Refresh token inválido o expirado"
