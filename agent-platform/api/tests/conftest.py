"""Shared agent-platform test configuration."""

import os
import sys

# Asegurar que /app esté en el path para resolver imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("FASTAPI_ENV", "testing")
# Variables mínimas para que settings no falle al importar
os.environ.setdefault(
    "POSTGRES_DSN",
    os.environ.get(
        "AGENT_TEST_POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost/test"
    ),
)
os.environ.setdefault("FASTAPI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "test-wa-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-app-secret")

import pytest


@pytest.fixture
def request_id():
    return "test-req-001"


@pytest.fixture
def phone_number():
    return "5493875296587"
