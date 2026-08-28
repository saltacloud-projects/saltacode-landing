"""
Regresión (integración) — Tracking de entrega de WhatsApp (message_statuses).

Verifica el problema de "dice enviado pero no llega": el HTTP 200 al enviar solo
es `accepted`; la entrega real llega async por webhooks y debe persistirse.

Estos tests usan la DB real del contenedor (AsyncSessionLocal → PostgreSQL,
porque delivery_status usa pg_insert/ON CONFLICT). Son herméticos: usan
meta_message_id efímeros (wamid.test.<uuid>) y limpian al final.

Ejecutar (dentro del contenedor, con Postgres):
    docker compose exec -T fastapi pytest tests/test_delivery_status.py -v
"""

import os
import uuid

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.message_status import MessageStatus
from app.services import delivery_status


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    """pytest-asyncio usa un event loop por test; el pool de asyncpg no se puede
    reutilizar entre loops (RuntimeError: Event loop is closed). Cerramos el pool
    tras cada test para que el siguiente abra conexiones frescas en su loop."""
    yield
    from app.core.database import engine

    await engine.dispose()


async def _fetch(mid: str) -> MessageStatus | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(MessageStatus).where(MessageStatus.meta_message_id == mid)
            )
        ).scalar_one_or_none()


async def _cleanup(mid: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(MessageStatus).where(MessageStatus.meta_message_id == mid)
        )
        await db.commit()


class TestDeliveryStatusLifecycle:
    async def test_outbound_luego_delivered_luego_failed(self):
        mid = f"wamid.test.{uuid.uuid4().hex}"
        try:
            # 1. Envío: queda 'accepted' con contexto.
            await delivery_status.record_outbound(
                meta_message_id=mid,
                phone="549test",
                recipient_name="Tester",
                context="seguimiento de solicitud",
            )
            row = await _fetch(mid)
            assert row is not None
            assert row.status == "accepted"
            assert row.context == "seguimiento de solicitud"
            assert row.recipient_name == "Tester"

            # 2. Webhook 'delivered': se actualiza la misma fila + status_at.
            n = await delivery_status.upsert_statuses(
                [
                    {
                        "message_id": mid,
                        "recipient": "549test",
                        "status": "delivered",
                        "timestamp": "1700000000",
                    }
                ]
            )
            assert n == 1
            row = await _fetch(mid)
            assert row.status == "delivered"
            assert row.status_at is not None

            # 3. Webhook 'failed' con código de error (ej: número no en WhatsApp).
            await delivery_status.upsert_statuses(
                [
                    {
                        "message_id": mid,
                        "recipient": "549test",
                        "status": "failed",
                        "error_code": "131026",
                        "error_title": "no está en WhatsApp",
                    }
                ]
            )
            row = await _fetch(mid)
            assert row.status == "failed"
            assert row.error_code == "131026"
        finally:
            await _cleanup(mid)

    async def test_status_sin_outbound_crea_fila(self):
        # Si llega un status sin envío previo, se crea la fila con el recipient.
        mid = f"wamid.test.{uuid.uuid4().hex}"
        try:
            n = await delivery_status.upsert_statuses(
                [
                    {
                        "message_id": mid,
                        "recipient": "549xyz",
                        "status": "sent",
                    }
                ]
            )
            assert n == 1
            row = await _fetch(mid)
            assert row is not None
            assert row.status == "sent"
            assert row.phone == "549xyz"
        finally:
            await _cleanup(mid)

    async def test_record_outbound_sin_id_es_noop(self):
        # Sin meta_message_id no hay nada que correlacionar: no debe romper.
        await delivery_status.record_outbound(meta_message_id=None, phone="549test")
        # upsert con lista vacía retorna 0
        assert await delivery_status.upsert_statuses([]) == 0
