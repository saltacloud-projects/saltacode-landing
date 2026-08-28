"""
Regresión — Memoria rodante (resumen de largo plazo).

Cubre la lógica PURA (sin DB ni OpenAI):
  - Inyección del resumen en el system prompt del agent_loop.
  - Selección de mensajes "envejecidos" que entran al resumen (se dejan
    siempre los últimos N de la ventana activa).

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
from app.services.conversation import _aged_out_messages

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


class TestAgedOutSelection:
    """Se resumen los mensajes que salieron de la ventana; el resto se conserva."""

    def test_menos_que_la_ventana_no_envejece_nada(self):
        assert _aged_out_messages(list(range(5)), keep_in_window=20) == []

    def test_igual_a_la_ventana_no_envejece_nada(self):
        assert _aged_out_messages(list(range(20)), keep_in_window=20) == []

    def test_excedente_envejece_los_mas_viejos(self):
        rows = list(range(25))  # 0..24
        aged = _aged_out_messages(rows, keep_in_window=20)
        # Se conservan los últimos 20 (5..24); envejecen los primeros 5 (0..4).
        assert aged == [0, 1, 2, 3, 4]

    def test_keep_cero_envejece_todo(self):
        assert _aged_out_messages([1, 2, 3], keep_in_window=0) == [1, 2, 3]
