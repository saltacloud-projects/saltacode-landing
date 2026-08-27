"""
Tests de sincronización runtime para tools declarativas http_api.

La DB (`tool_registry`) es fuente de verdad, pero el agent_loop invoca adapters
registrados en memoria. Estos tests cubren que el sync refleje altas/cambios y
limpie declarativas stale sin reiniciar el proceso.
"""

import os
from types import SimpleNamespace

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("FASTAPI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")

from app.services.tools.dynamic import sync_http_api_tools
from app.services.tools.registry import tool_registry


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _Result(self._rows)


def _cfg(name: str):
    return SimpleNamespace(
        tool_name=name,
        http_config={
            "method": "GET",
            "path": f"/api/{name}/",
            "param_location": "query",
        },
        result_type="json",
        timeout_seconds=10,
        params_schema={},
    )


async def test_sync_registers_http_api_tool():
    tool_registry.unregister("test_dynamic_a")

    count = await sync_http_api_tools(_Db([_cfg("test_dynamic_a")]))

    assert count == 1
    assert tool_registry.get("test_dynamic_a") is not None


async def test_sync_unregisters_stale_http_api_tool():
    await sync_http_api_tools(_Db([_cfg("test_dynamic_b")]))
    assert tool_registry.get("test_dynamic_b") is not None

    await sync_http_api_tools(_Db([]))

    assert tool_registry.get("test_dynamic_b") is None
