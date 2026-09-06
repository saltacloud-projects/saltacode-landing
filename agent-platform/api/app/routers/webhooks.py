"""Meta WhatsApp ingress adapter."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.webhook_security import InvalidWebhookSignature, verify_meta_signature
from app.dependencies import get_db
from app.schemas.inbound import InboundRouteContext
from app.services.agent_runtime import (
    AgentRuntimeUnavailable,
    ResolvedChannelRoute,
    agent_runtime_resolver,
)
from app.services.whatsapp import (
    WhatsAppConnectionContext,
    WhatsAppConnectionUnavailable,
    WhatsAppInboundPayloadInvalid,
    whatsapp_service,
)
from app.services.whatsapp_inbox import (
    WhatsAppInboxUnavailable,
    whatsapp_inbox_service,
)

router = APIRouter(tags=["webhooks"])
logger = logging.getLogger(__name__)
ROUTE_KEY_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,119}$"


async def _resolve_whatsapp_channel_route(
    db: AsyncSession, route_key: str
) -> tuple[ResolvedChannelRoute, WhatsAppConnectionContext]:
    try:
        resolved = await agent_runtime_resolver.resolve_channel_route(
            db, "whatsapp", route_key
        )
        connection = whatsapp_service.resolve_connection(
            resolved.connection, route_key=route_key
        )
    except (AgentRuntimeUnavailable, WhatsAppConnectionUnavailable) as exc:
        logger.warning(
            "whatsapp_route_unavailable",
            extra={"route_key": route_key, "reason": str(exc)},
        )
        raise HTTPException(
            status_code=503, detail="WhatsApp route is unavailable"
        ) from exc
    return resolved, connection


def _payload_phone_number_ids(payload: dict) -> set[str]:
    account_ids: set[str] = set()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            phone_number_id = ((change.get("value") or {}).get("metadata") or {}).get(
                "phone_number_id"
            )
            if phone_number_id:
                account_ids.add(str(phone_number_id))
    return account_ids


def _verify_account(payload: dict, connection: WhatsAppConnectionContext) -> None:
    if _payload_phone_number_ids(payload) != {connection.phone_number_id}:
        logger.warning(
            "whatsapp_account_rejected",
            extra={"route_key": connection.route_key},
        )
        raise HTTPException(status_code=403, detail="Webhook account mismatch")


async def _process_payload(
    payload: dict,
    *,
    db: AsyncSession,
    channel_route: ResolvedChannelRoute,
    connection: WhatsAppConnectionContext,
) -> dict[str, str]:
    if connection.connection_id is None or connection.route_key is None:
        raise HTTPException(status_code=503, detail="WhatsApp route is unavailable")
    route = InboundRouteContext(
        route_key=connection.route_key,
        channel_route_id=channel_route.route.id,
        channel_connection_id=connection.connection_id,
    )
    try:
        messages = whatsapp_service.normalize_messages(payload, route=route)
    except WhatsAppInboundPayloadInvalid as exc:
        raise HTTPException(status_code=400, detail="Invalid WhatsApp message") from exc

    if not messages:
        statuses = whatsapp_service.parse_statuses(payload)
        if statuses:
            from app.services.delivery_status import upsert_statuses

            await upsert_statuses(statuses)
            for status in statuses:
                logger.info(
                    "whatsapp_status",
                    extra={
                        "message_id": status.get("message_id"),
                        "status": status.get("status"),
                        "error_code": status.get("error_code"),
                        "route_key": connection.route_key if connection else None,
                    },
                )
            return {"status": "status_recorded"}
        logger.debug(
            "whatsapp_non_message_event", extra={"payload_keys": list(payload.keys())}
        )
        return {"status": "ignored"}

    accepted_count = 0
    for message in messages:
        logger.info(
            "whatsapp_inbound_received",
            extra={
                "content_type": message.content_type.value,
                "message_id": message.provider_message_id,
                "has_interaction": message.interaction_id is not None,
                "content_chars": len(message.content),
                "route_key": message.route.route_key,
            },
        )
        try:
            accepted = await whatsapp_inbox_service.enqueue(
                db,
                message=message,
            )
        except WhatsAppInboxUnavailable as exc:
            logger.error(
                "whatsapp_inbox_enqueue_failed",
                extra={"route_key": connection.route_key},
            )
            raise HTTPException(
                status_code=503, detail="WhatsApp message was not accepted"
            ) from exc
        if accepted.duplicate:
            logger.info(
                "whatsapp_inbound_duplicate_ignored",
                extra={
                    "message_id": message.provider_message_id,
                    "route_key": connection.route_key,
                },
            )
            continue
        accepted_count += 1
        logger.info(
            "whatsapp_inbound_enqueued",
            extra={
                "job_id": str(accepted.job_id),
                "message_id": message.provider_message_id,
                "route_key": connection.route_key,
            },
        )
    return {"status": "received" if accepted_count else "duplicate"}


@router.get("/whatsapp/{route_key}")
async def whatsapp_route_verify(
    route_key: str = Path(pattern=ROUTE_KEY_PATTERN),
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
    db: AsyncSession = Depends(get_db),
):
    """Verify the preferred persisted WhatsApp route."""
    _, connection = await _resolve_whatsapp_channel_route(db, route_key)
    challenge = whatsapp_service.verify_webhook(
        hub_mode,
        hub_verify_token,
        hub_challenge,
        verify_token=connection.verify_token,
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="Invalid verification token")
    return Response(content=challenge, media_type="text/plain")


@router.post("/whatsapp/{route_key}", status_code=200)
async def whatsapp_route_inbound(
    request: Request,
    route_key: str = Path(pattern=ROUTE_KEY_PATTERN),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate and dispatch one persisted WhatsApp route."""
    channel_route, connection = await _resolve_whatsapp_channel_route(db, route_key)
    raw_body = await request.body()
    try:
        verify_meta_signature(
            raw_body=raw_body,
            signature_header=request.headers.get("X-Hub-Signature-256"),
            app_secret=connection.app_secret,
        )
    except InvalidWebhookSignature as exc:
        logger.warning("whatsapp_signature_rejected", extra={"route_key": route_key})
        raise HTTPException(
            status_code=401, detail="Invalid webhook signature"
        ) from exc
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    _verify_account(payload, connection)
    return await _process_payload(
        payload,
        db=db,
        channel_route=channel_route,
        connection=connection,
    )
