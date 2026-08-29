"""
Regresión — Capa de conocimiento del prompt (knowledge_blocks + fallback).

Mitiga el riesgo de que una edición del template (en DB o en código) deje
placeholders sin resolver o se desincronice del builder del agent_loop.

NO depende de OpenAI ni DB real: prueba el contenido por defecto y la
lógica pura de resolución/parseo.

Ejecutar:
    docker compose exec -T fastapi pytest tests/test_knowledge_prompt.py -v
"""

import os
import re

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")

from types import SimpleNamespace

import pytest

from app.bootstrap import DEFAULT_BLOCKS
from app.core.temporal_context import build_temporal_context
from app.services.knowledge import (
    KnowledgeService,
    _resolve_placeholders,
    _unresolved_placeholders,
)

# Captura el nombre interno (sin llaves) para comparar con las claves del builder.
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def _builder_keys() -> set[str]:
    """Claves que el contexto temporal provee a knowledge placeholders."""
    return set(build_temporal_context().keys())


def _full_ctx() -> dict[str, str]:
    return build_temporal_context()


class TestBootstrapKnowledge:
    def test_bootstrap_placeholders_are_supported_by_the_runtime_builder(self):
        for _key, _title, content, _sort_order in DEFAULT_BLOCKS:
            missing = set(_PLACEHOLDER_RE.findall(content)) - _builder_keys()
            assert not missing
            assert (
                _unresolved_placeholders(_resolve_placeholders(content, _full_ctx()))
                == []
            )

    def test_bootstrap_owns_the_current_neutral_knowledge_set(self):
        keys = {key for key, _title, _content, _sort_order in DEFAULT_BLOCKS}
        assert keys == {"company_profile", "services", "commercial_policy"}


class TestResolver:
    def test_no_toca_llaves_desconocidas(self):
        out = _resolve_placeholders(
            "hola {desconocido} {fecha_actual}", {"fecha_actual": "X"}
        )
        assert out == "hola {desconocido} X"

    def test_detecta_placeholders_sin_resolver(self):
        assert _unresolved_placeholders("texto {regiones} fin") == ["{regiones}"]
        assert _unresolved_placeholders("sin placeholders") == []

    @pytest.mark.asyncio
    async def test_resuelve_bloques_sin_perder_identidad_semantica(self):
        service = KnowledgeService()
        blocks = [
            SimpleNamespace(
                key="seguimiento_solicitudes",
                title="Seguimiento de solicitudes",
                content="Fecha: {fecha_actual}",
                sort_order=70,
            ),
            SimpleNamespace(
                key="formato_respuestas",
                title="Formato de respuestas",
                content="Formato propio",
                sort_order=90,
            ),
        ]

        class FakeDb:
            async def execute(self, _stmt):
                return SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: blocks),
                )

        resolved = await service.build_resolved_knowledge(FakeDb(), _full_ctx())

        assert [block.key for block in resolved] == [
            "seguimiento_solicitudes",
            "formato_respuestas",
        ]
        assert resolved[0].title == "Seguimiento de solicitudes"
        assert "{fecha_actual}" not in resolved[0].content
        assert service.compose_resolved_knowledge(resolved) == (
            f"Fecha: {_full_ctx()['fecha_actual']}\n\nFormato propio"
        )
