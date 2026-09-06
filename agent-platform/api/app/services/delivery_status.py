"""
Agent Platform — DeliveryStatusService

Persiste el estado de entrega real de los mensajes salientes de WhatsApp en la
tabla `message_statuses`. Resuelve el problema de "dice enviado pero no llega":
el HTTP 200 al enviar solo significa que Meta aceptó el mensaje; la entrega real
(`sent` → `delivered` → `read`, o `failed`) llega async por webhooks de status.

Flujo:
  1. Al enviar una notificación, `record_outbound()` inserta una fila con
     status `accepted` y el contexto de la entrega.
  2. Cuando Meta manda el webhook de status, `upsert_statuses()` actualiza esa
     misma fila (match por `meta_message_id`) con el estado real y el error si
     falló (ej: 131026 = el número no está en WhatsApp).

Todas las operaciones son best-effort: si fallan, se loguea y se sigue (nunca
deben romper el envío ni la respuesta 200 al webhook de Meta).
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.models.message_status import MessageStatus

logger = logging.getLogger(__name__)


async def record_outbound(
    *,
    meta_message_id: str | None,
    phone: str,
    recipient_name: str | None = None,
    kind: str = "template",
    context: str | None = None,
) -> None:
    """
    Registra un mensaje saliente recién enviado (status inicial `accepted`).
    Idempotente por meta_message_id: si ya existe (porque llegó antes un status),
    enriquece el contexto pero NO pisa el status real.
    """
    if not meta_message_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                pg_insert(MessageStatus)
                .values(
                    id=uuid.uuid4(),
                    meta_message_id=meta_message_id,
                    phone=phone,
                    recipient_name=recipient_name,
                    kind=kind,
                    context=context,
                    status="accepted",
                )
                .on_conflict_do_update(
                    index_elements=["meta_message_id"],
                    set_={
                        "recipient_name": recipient_name,
                        "context": context,
                        "kind": kind,
                    },
                )
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as e:
        logger.warning(
            "message_status_record_outbound_error",
            extra={"error": str(e), "meta_message_id": meta_message_id},
        )


async def upsert_statuses(statuses: list[dict]) -> int:
    """
    Aplica una lista de eventos de status de Meta (last-write-wins por message_id).
    Si no existe fila para el message_id (status llegó sin outbound previo), la crea
    poblando el phone con el recipient_id del status.
    Retorna la cantidad de eventos procesados.
    """
    if not statuses:
        return 0
    n = 0
    try:
        async with AsyncSessionLocal() as db:
            for s in statuses:
                mid = s.get("message_id")
                if not mid:
                    continue
                ts = None
                raw_ts = s.get("timestamp")
                if raw_ts:
                    try:
                        ts = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
                    except (ValueError, TypeError):
                        ts = None
                status = s.get("status") or "unknown"
                stmt = (
                    pg_insert(MessageStatus)
                    .values(
                        id=uuid.uuid4(),
                        meta_message_id=mid,
                        phone=s.get("recipient") or "",
                        kind="outbound",
                        status=status,
                        error_code=s.get("error_code"),
                        error_title=s.get("error_title"),
                        status_at=ts,
                    )
                    .on_conflict_do_update(
                        index_elements=["meta_message_id"],
                        set_={
                            "status": status,
                            "error_code": s.get("error_code"),
                            "error_title": s.get("error_title"),
                            "status_at": ts,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )
                )
                await db.execute(stmt)
                n += 1
            await db.commit()
    except Exception as e:
        logger.warning("message_status_upsert_error", extra={"error": str(e)})
    return n
