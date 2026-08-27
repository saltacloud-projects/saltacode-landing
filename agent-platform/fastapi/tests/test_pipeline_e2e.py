"""
Tests E2E focalizados del pipeline — sin dependencias externas reales.

Cubre piezas que NO requieren PostgreSQL ni OpenAI ni Meta:
  - `parse_inbound`: preserva interactive_id y maneja todos los tipos canónicos.
  - Backpressure: `concurrency.get_semaphores_state()` reporta slots libres.
  - Schema de tools: `llm_summary` se excluye de la serialización pública.
  - Idempotencia: el webhook descarta duplicados por message_id.

Para tests que requieren DB o servicios externos, ver instrucciones en
`docs/runbook.md`.

Ejecutar:
    docker compose exec api pytest tests/test_pipeline_e2e.py -v
"""

import asyncio
import os

import pytest

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("SIM_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")
os.environ.setdefault("FASTAPI_API_KEY", "test-key")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost/test")


# ═════════════════════════════════════════════════════════════════════════════
# parse_inbound — preserva interactive_id
# ═════════════════════════════════════════════════════════════════════════════


class TestParseInboundInteractive:
    def test_button_reply_preserves_id_and_title(self):
        from app.services.whatsapp import whatsapp_service

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "5493875296587",
                                        "id": "wamid.btn",
                                        "timestamp": "1700000000",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {
                                                "id": "btn_menu",
                                                "title": "📋 Ver opciones",
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        msg = whatsapp_service.parse_inbound(payload)
        assert msg is not None
        assert msg["interactive_id"] == "btn_menu"
        assert "Ver opciones" in msg["content"]
        assert msg["input_type"] == "text"

    def test_list_reply_preserves_id(self):
        from app.services.whatsapp import whatsapp_service

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "5493875296587",
                                        "id": "wamid.list",
                                        "timestamp": "1700000000",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "list_reply",
                                            "list_reply": {
                                                "id": "menu_tool_sim_caja_saldo",
                                                "title": "Saldo de caja",
                                                "description": "Caja por sucursal",
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        msg = whatsapp_service.parse_inbound(payload)
        assert msg["interactive_id"] == "menu_tool_sim_caja_saldo"
        assert msg["content"] == "Saldo de caja"

    def test_audio_extracts_media_id(self):
        from app.services.whatsapp import whatsapp_service

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "5493875296587",
                                        "id": "wamid.audio",
                                        "timestamp": "1700000000",
                                        "type": "audio",
                                        "audio": {"id": "media-id-1234"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        msg = whatsapp_service.parse_inbound(payload)
        assert msg["input_type"] == "audio"
        assert msg["audio_media_id"] == "media-id-1234"
        assert msg["interactive_id"] is None

    def test_status_event_returns_none(self):
        """Status updates de Meta no son mensajes — deben ignorarse."""
        from app.services.whatsapp import whatsapp_service

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [{"id": "wamid.s", "status": "delivered"}]
                            }
                        }
                    ]
                }
            ]
        }
        assert whatsapp_service.parse_inbound(payload) is None


# ═════════════════════════════════════════════════════════════════════════════
# Schema de tools — llm_summary y file_mime excluidos del JSON público
# ═════════════════════════════════════════════════════════════════════════════


class TestToolResultSchema:
    def test_llm_summary_excluded_from_model_dump(self):
        """El llm_summary y file_content/file_mime no deben salir en el JSON."""
        from app.schemas.tools import ToolResult

        result = ToolResult(
            request_id="r1",
            tool_name="sim_test",
            status="success",
            result={"items": list(range(100))},  # data completa, no truncada
            llm_summary={"items_count": 100, "first_3": [0, 1, 2]},
            file_content=b"fake excel bytes",
            file_name="reporte.xlsx",
            file_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        dumped = result.model_dump()
        assert "llm_summary" not in dumped
        assert "file_content" not in dumped
        assert "file_name" not in dumped
        assert "file_mime" not in dumped
        # `result` con la data completa SÍ debe estar
        assert dumped["result"]["items"] == list(range(100))

    def test_default_file_mime_is_excel(self):
        from app.schemas.tools import DEFAULT_FILE_MIME

        assert (
            DEFAULT_FILE_MIME
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Backpressure (semáforos)
# ═════════════════════════════════════════════════════════════════════════════


class TestConcurrencySemaphores:
    def test_initial_state_all_slots_free(self):
        """Al arrancar, todos los semáforos deben tener todos sus slots libres."""
        from app.core.concurrency import (
            MAX_CONCURRENT_INTEGRATION_CALLS,
            MAX_CONCURRENT_LLM_CALLS,
            MAX_CONCURRENT_PIPELINES,
            MAX_CONCURRENT_WHATSAPP_CALLS,
            get_semaphores_state,
        )

        state = get_semaphores_state()
        assert state["pipeline_free"] == MAX_CONCURRENT_PIPELINES
        assert state["llm_free"] == MAX_CONCURRENT_LLM_CALLS
        assert state["integration_free"] == MAX_CONCURRENT_INTEGRATION_CALLS
        assert state["whatsapp_free"] == MAX_CONCURRENT_WHATSAPP_CALLS

    def test_limits_are_reasonable_for_small_team(self):
        """Los límites deben ser razonables: ni demasiado bajos ni excesivos."""
        from app.core.concurrency import (
            MAX_CONCURRENT_INTEGRATION_CALLS,
            MAX_CONCURRENT_LLM_CALLS,
            MAX_CONCURRENT_PIPELINES,
            MAX_CONCURRENT_WHATSAPP_CALLS,
        )

        # 20-50 usuarios concurrentes → 5-50 pipelines simultáneos es razonable
        assert 5 <= MAX_CONCURRENT_PIPELINES <= 50
        # OpenAI tiene rate limits; mantener bajo para evitar 429
        assert 2 <= MAX_CONCURRENT_LLM_CALLS <= 30
        # Fuentes externas necesitan backpressure independiente del LLM.
        assert 2 <= MAX_CONCURRENT_INTEGRATION_CALLS <= 30
        # WhatsApp Graph API: ~80 msg/s, semaforo en memoria por proceso
        assert 5 <= MAX_CONCURRENT_WHATSAPP_CALLS <= 50

    @pytest.mark.asyncio
    async def test_pipeline_semaphore_actually_limits(self):
        """Verifica que el semáforo de pipeline efectivamente bloquea más allá del límite."""
        from app.core.concurrency import MAX_CONCURRENT_PIPELINES, pipeline_semaphore

        # Si saturamos el semáforo, la siguiente adquisición espera
        in_flight = 0
        peak = 0

        async def hold(duration: float):
            nonlocal in_flight, peak
            async with pipeline_semaphore:
                in_flight += 1
                peak = max(peak, in_flight)
                await asyncio.sleep(duration)
                in_flight -= 1

        # Lanzar el doble del máximo
        tasks = [hold(0.05) for _ in range(MAX_CONCURRENT_PIPELINES * 2)]
        await asyncio.gather(*tasks)
        assert peak <= MAX_CONCURRENT_PIPELINES


# ═════════════════════════════════════════════════════════════════════════════
# Idempotencia integrada — webhook descarta duplicados
# ═════════════════════════════════════════════════════════════════════════════


class TestWebhookIdempotency:
    @pytest.mark.asyncio
    async def test_claim_message_id_blocks_second_call(self):
        """Reproduce el patrón del webhook: segunda llamada con el mismo id retorna False."""
        from app.core.dedup_lock import claim_message_id
        from tests.test_dedup_lock import FakeRedis  # type: ignore

        redis = FakeRedis()
        first = await claim_message_id(redis, "wamid.repeat")
        second = await claim_message_id(redis, "wamid.repeat")
        third = await claim_message_id(redis, "wamid.repeat")
        assert first is True
        assert second is False
        assert third is False
