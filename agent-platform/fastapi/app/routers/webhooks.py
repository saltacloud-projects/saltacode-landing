"""Meta WhatsApp ingress adapter."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dedup_lock import claim_message_id
from app.core.webhook_security import InvalidWebhookSignature, verify_meta_signature
from app.dependencies import get_db
from app.services.agent_runtime import (
    AgentRuntimeUnavailable,
    ResolvedAgentRoute,
    ResolvedChannelRoute,
    agent_runtime_resolver,
)
from app.services.pipeline import pipeline_service
from app.services.whatsapp import (
    WhatsAppConnectionContext,
    WhatsAppConnectionUnavailable,
    whatsapp_service,
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


async def _resolve_runtime(
    db: AsyncSession, channel_route: ResolvedChannelRoute, *, route_key: str
) -> ResolvedAgentRoute:
    try:
        runtime = await agent_runtime_resolver.resolve_agent(
            db, channel_route.route.agent_id, require_public=False
        )
    except AgentRuntimeUnavailable as exc:
        logger.warning(
            "whatsapp_runtime_unavailable",
            extra={"route_key": route_key, "reason": str(exc)},
        )
        raise HTTPException(
            status_code=503, detail="WhatsApp route is unavailable"
        ) from exc
    return ResolvedAgentRoute(channel_route.route, channel_route.connection, runtime)


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
    request: Request,
    payload: dict,
    *,
    db: AsyncSession | None = None,
    channel_route: ResolvedChannelRoute | None = None,
    connection: WhatsAppConnectionContext | None = None,
) -> dict[str, str]:
    msg = whatsapp_service.parse_inbound(payload)
    if msg is None:
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

    resolved_route = None
    if channel_route is not None:
        if db is None or connection is None or connection.route_key is None:
            raise HTTPException(status_code=503, detail="WhatsApp route is unavailable")
        resolved_route = await _resolve_runtime(
            db, channel_route, route_key=connection.route_key
        )

    logger.info(
        "whatsapp_inbound_received",
        extra={
            "input_type": msg.get("input_type"),
            "message_id": msg.get("message_id"),
            "interactive_id": msg.get("interactive_id"),
            "content_chars": len(msg.get("content") or ""),
            "route_key": connection.route_key if connection else None,
        },
    )
    redis = getattr(request.app.state, "redis", None)
    dedup_id = msg.get("message_id")
    if resolved_route is not None and dedup_id:
        dedup_id = f"{resolved_route.route.id}:{dedup_id}"
    if not await claim_message_id(redis, dedup_id):
        logger.info(
            "whatsapp_inbound_duplicate_ignored",
            extra={
                "message_id": msg.get("message_id"),
                "route_key": connection.route_key if connection else None,
            },
        )
        return {"status": "duplicate"}

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
            resolved_runtime=resolved_route.runtime if resolved_route else None,
            whatsapp_connection=connection,
            route_key=connection.route_key if connection else None,
            channel_route_id=(resolved_route.route.id if resolved_route else None),
        )
    )
    return {"status": "received"}


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
        request,
        payload,
        db=db,
        channel_route=channel_route,
        connection=connection,
    )


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """Release-A fallback for the former environment-backed webhook."""
    logger.warning("legacy_whatsapp_webhook_without_route_key")
    challenge = whatsapp_service.verify_webhook(
        hub_mode, hub_verify_token, hub_challenge
    )
    if challenge is None:
        raise HTTPException(status_code=403, detail="Invalid verification token")
    return Response(content=challenge, media_type="text/plain")


@router.post("/whatsapp", status_code=200)
async def whatsapp_inbound(request: Request):
    """Release-A fallback; new Meta webhooks must use a persisted route key."""
    logger.warning("legacy_whatsapp_webhook_without_route_key")
    raw_body = await request.body()
    try:
        verify_meta_signature(
            raw_body=raw_body,
            signature_header=request.headers.get("X-Hub-Signature-256"),
            app_secret=settings.whatsapp_app_secret,
        )
    except InvalidWebhookSignature as exc:
        logger.warning("whatsapp_signature_rejected", extra={"legacy": True})
        raise HTTPException(
            status_code=401, detail="Invalid webhook signature"
        ) from exc
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    return await _process_payload(request, payload)
