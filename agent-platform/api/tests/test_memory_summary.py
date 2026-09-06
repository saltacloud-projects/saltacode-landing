"""
Regresión — Memoria rodante (resumen de largo plazo).

Cubre la lógica PURA (sin DB ni OpenAI) de inyección del resumen en el system
prompt del agent_loop.

Ejecutar:
    docker compose exec -T fastapi pytest tests/test_memory_summary.py -v
"""

import os

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")


from app.core.temporal_context import build_temporal_context
from app.services.agent_loop import _build_agent_system_prompt

_MEM_HEADER = "MEMORIA DE CONVERSACIONES PREVIAS"
_TEMPORAL_CTX = build_temporal_context()


class TestSummaryInjection:
    """El resumen rodante solo aparece en el prompt cuando existe."""

    def test_con_resumen_se_inyecta(self):
        out = _build_agent_system_prompt(
            None,
            "DIRECTIVAS",
            _TEMPORAL_CTX,
            "Hablamos del seguimiento de una solicitud.",
        )
        assert _MEM_HEADER in out
        assert "Hablamos del seguimiento de una solicitud." in out
        # Las directivas se preservan.
        assert "DIRECTIVAS" in out

    def test_sin_resumen_no_hay_bloque(self):
        assert _MEM_HEADER not in _build_agent_system_prompt(
            None,
            "DIRECTIVAS",
            _TEMPORAL_CTX,
            None,
        )

    def test_resumen_vacio_no_hay_bloque(self):
        assert _MEM_HEADER not in _build_agent_system_prompt(
            None,
            "DIRECTIVAS",
            _TEMPORAL_CTX,
            "",
        )

    def test_fecha_autoritativa_precede_memoria_desactualizada(self):
        stale = "Hoy es 2026-07-22 según una conversación anterior."
        out = _build_agent_system_prompt(None, "DIRECTIVAS", _TEMPORAL_CTX, stale)
        assert f"Fecha actual exacta: {_TEMPORAL_CTX['fecha_actual']}." in out
        assert "PRECEDENCIA OBLIGATORIA" in out
        assert out.index("CONTEXTO TEMPORAL AUTORITATIVO") < out.index(_MEM_HEADER)
