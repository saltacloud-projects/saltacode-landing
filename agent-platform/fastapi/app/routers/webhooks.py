"""Meta WhatsApp ingress adapter."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.config import settings
from app.core.dedup_lock import claim_message_id
from app.core.webhook_security import InvalidWebhookSignature, verify_meta_signature
from app.services.pipeline import pipeline_service
from app.services.whatsapp import whatsapp_service

router = APIRouter(tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """
    Meta llama a este endpoint para verificar el webhook.
    Debe responder con el hub.challenge si el token es válido.
    """
    challenge = whatsapp_service.verify_webhook(
        hub_mode, hub_verify_token, hub_challenge
    )
    logger.info(
        "whatsapp_verify",
        extra={"hub_mode": hub_mode, "verified": challenge is not None},
    )
    if challenge is None:
        logger.error("whatsapp_verify_failed", extra={"hub_mode": hub_mode})
        raise HTTPException(status_code=403, detail="Token de verificación inválido")
    return Response(content=challenge, media_type="text/plain")


@router.post("/whatsapp", status_code=200)
async def whatsapp_inbound(request: Request):
    """
    Meta envía mensajes entrantes de WhatsApp a este endpoint.
    Responde 200 inmediatamente y procesa el mensaje en background.
    """
    raw_body = await request.body()
    try:
        verify_meta_signature(
            raw_body=raw_body,
            signature_header=request.headers.get("X-Hub-Signature-256"),
            app_secret=settings.whatsapp_app_secret,
        )
    except InvalidWebhookSignature as exc:
        logger.warning("whatsapp_signature_rejected", extra={"reason": str(exc)})
        raise HTTPException(
            status_code=401, detail="Invalid webhook signature"
        ) from exc
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    # El payload de Meta contiene datos del usuario (texto del mensaje, números,
    # nombres). Lo dejamos en DEBUG para que en producción (LOG_LEVEL=INFO) no
    # quede expuesto en los logs. Para troubleshooting se baja LOG_LEVEL a DEBUG.
    logger.debug(
        "whatsapp_inbound_payload",
        extra={
            "payload": payload,
        },
    )

    # Meta espera siempre un 200 rápido o reintenta
    msg = whatsapp_service.parse_inbound(payload)
    # `msg` también puede contener el contenido del mensaje del usuario.
    # En INFO logueamos solo metadata (input_type, message_id, interactive_id)
    # y el contenido completo queda en DEBUG.
    if msg is not None:
        logger.debug(
            "whatsapp_inbound_parsed_full",
            extra={"parsed_message": msg},
        )
    if msg is None:
        # Puede ser un webhook de STATUS de entrega (sent/delivered/read/failed).
        # Antes se descartaban; ahora los persistimos para tener visibilidad real
        # de quién recibió cada reporte y por qué falló cuando falla.
        statuses = whatsapp_service.parse_statuses(payload)
        if statuses:
            from app.services.delivery_status import upsert_statuses

            await upsert_statuses(statuses)
            for s in statuses:
                logger.info(
                    "whatsapp_status",
                    extra={
                        "message_id": s.get("message_id"),
                        "recipient": s.get("recipient"),
                        "status": s.get("status"),
                        "error_code": s.get("error_code"),
                    },
                )
            return {"status": "status_recorded"}
        # reactions, otros eventos no-mensaje — ignorar silenciosamente
        logger.debug(
            "whatsapp_non_message_event", extra={"payload_keys": list(payload.keys())}
        )
        return {"status": "ignored"}

    logger.info(
        "whatsapp_inbound_received",
        extra={
            "phone": msg["phone_number"],
            "input_type": msg.get("input_type"),
            "message_id": msg.get("message_id"),
            "interactive_id": msg.get("interactive_id"),
            "content_chars": len(msg.get("content") or ""),
        },
    )

    # Redis disponible via app.state (inicializado en el lifespan de main.py)
    redis = getattr(request.app.state, "redis", None)

    # Idempotencia: Meta puede reintentar el mismo webhook si no recibe 200
    # rápido o por su propia política de reintentos. SET NX en Redis garantiza
    # que solo el primero pasa al pipeline; el resto se ignora silenciosamente.
    # Cubre ambos paths montados (/webhooks/whatsapp y /webhook/whatsapp).
    is_new = await claim_message_id(redis, msg.get("message_id"))
    if not is_new:
        logger.info(
            "whatsapp_inbound_duplicate_ignored",
            extra={"message_id": msg.get("message_id"), "phone": msg["phone_number"]},
        )
        return {"status": "duplicate"}

    # Lanzar pipeline en background — no bloquear respuesta a Meta
    asyncio.create_task(
        pipeline_service.process_whatsapp_message(
            phone=msg["phone_number"],
            content=msg["content"],
            message_id=msg["message_id"],
            input_type=msg["input_type"],
            audio_media_id=msg.get("audio_media_id"),
            interactive_id=msg.get("interactive_id"),
            quoted_id=msg.get("quoted_id"),
            redis=redis,
        )
    )

    return {"status": "received"}
