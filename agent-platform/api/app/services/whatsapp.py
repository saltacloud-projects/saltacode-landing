"""
Agent Platform — WhatsAppService
Integración con Meta Cloud API (WhatsApp Business).

Responsabilidades:
  - Verificar el webhook al configurarlo en Meta (GET challenge)
  - Parsear mensajes entrantes del payload de Meta (POST)
  - Emitir acuses de lectura e indicadores de escritura no críticos

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from app.config import settings
from app.core.concurrency import whatsapp_semaphore
from app.models.agent_runtime import ChannelConnection
from app.ports.inbound import InboundChannelAdapter
from app.schemas.agent_runtime import WhatsAppCredentials
from app.schemas.inbound import (
    InboundContentType,
    InboundMessageEnvelope,
    InboundReplyContext,
    InboundRouteContext,
)
from app.services.credentials import (
    CredentialDecryptError,
    CredentialStoreUnavailable,
    credential_cipher,
)

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Red de seguridad de formato: el LLM a veces devuelve markdown (**negrita**,
# viñetas, títulos) y WhatsApp no lo interpreta, dejando asteriscos literales
# feos. Esto limpia el texto saliente de forma determinística, sin depender de
# que el prompt convenza al modelo.
_MD_HEADER = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_MD_BOLD = re.compile(r"\*{1,3}(\S.*?\S|\S)\*{1,3}")
_MULTI_BLANK = re.compile(r"\n{3,}")
_INBOUND_TYPE_MAP = {
    "text": InboundContentType.TEXT,
    "interactive": InboundContentType.TEXT,
    "audio": InboundContentType.AUDIO,
    "voice": InboundContentType.AUDIO,
    "image": InboundContentType.IMAGE,
    "video": InboundContentType.VIDEO,
    "document": InboundContentType.FILE,
    "sticker": InboundContentType.IMAGE,
    "location": InboundContentType.TEXT,
}


class WhatsAppConnectionUnavailable(RuntimeError):
    """Raised when a persisted WhatsApp connection cannot be used safely."""


class WhatsAppInboundPayloadInvalid(ValueError):
    """An authenticated Meta payload contains an invalid message contract."""


@dataclass(frozen=True)
class WhatsAppConnectionContext:
    """Request-scoped delivery credentials; secret fields are excluded from repr."""

    connection_id: UUID | None
    phone_number_id: str
    access_token: str = field(repr=False)
    verify_token: str = field(repr=False)
    app_secret: str = field(repr=False)
    route_key: str | None = None


def sanitize_whatsapp_text(text: str) -> str:
    """
    Normaliza un texto saliente para que se vea natural en WhatsApp:
      - quita encabezados markdown (#..)
      - convierte viñetas (- / * / +) en '• '
      - quita el énfasis markdown (**x**, *x*) dejando el contenido
      - elimina cualquier asterisco suelto remanente
    Garantiza que NUNCA llegue un '*' o '**' literal al usuario.
    """
    if not text:
        return text
    t = _MD_HEADER.sub("", text)
    t = _MD_BULLET.sub("• ", t)
    for _ in range(3):  # desanidar **/* repetidos
        new = _MD_BOLD.sub(r"\1", t)
        if new == t:
            break
        t = new
    t = t.replace("*", "")
    t = _MULTI_BLANK.sub("\n\n", t)
    return t.strip()


class WhatsAppService(InboundChannelAdapter):
    channel = "whatsapp"

    def resolve_connection(
        self, connection: ChannelConnection, *, route_key: str
    ) -> WhatsAppConnectionContext:
        """Decrypt and validate a persisted WhatsApp connection for one request."""
        if connection.channel != "whatsapp" or not connection.is_active:
            raise WhatsAppConnectionUnavailable("whatsapp connection is unavailable")
        phone_number_id = (connection.external_account_id or "").strip()
        if not phone_number_id:
            raise WhatsAppConnectionUnavailable(
                "whatsapp external account is not configured"
            )
        try:
            raw = credential_cipher.decrypt(connection.encrypted_credentials)
            credentials = WhatsAppCredentials.model_validate(raw)
        except (
            CredentialDecryptError,
            CredentialStoreUnavailable,
            ValidationError,
        ) as exc:
            raise WhatsAppConnectionUnavailable(
                "whatsapp credentials are unavailable"
            ) from exc
        return WhatsAppConnectionContext(
            connection_id=connection.id,
            phone_number_id=phone_number_id,
            access_token=credentials.access_token,
            verify_token=credentials.verify_token,
            app_secret=credentials.app_secret,
            route_key=route_key,
        )

    @staticmethod
    def _delivery_context(
        connection: WhatsAppConnectionContext | None,
    ) -> WhatsAppConnectionContext | None:
        if connection is not None:
            return connection
        if not settings.whatsapp_token or not settings.whatsapp_phone_number_id:
            return None
        return WhatsAppConnectionContext(
            connection_id=None,
            phone_number_id=settings.whatsapp_phone_number_id,
            access_token=settings.whatsapp_token,
            verify_token=settings.whatsapp_verify_token,
            app_secret=settings.whatsapp_app_secret,
        )

    def verify_webhook(
        self,
        mode: str,
        token: str,
        challenge: str,
        *,
        verify_token: str | None = None,
    ) -> str | None:
        """
        Verifica el webhook de Meta. Retorna el challenge si es válido, None si no.
        Meta llama a este endpoint con GET al configurar o actualizar el webhook.
        """
        expected_token = (
            verify_token if verify_token is not None else settings.whatsapp_verify_token
        )
        if mode == "subscribe" and token == expected_token:
            logger.info("whatsapp_webhook_verified")
            return challenge
        logger.warning("whatsapp_webhook_verification_failed")
        return None

    def normalize_messages(
        self,
        payload: Mapping[str, Any],
        *,
        route: InboundRouteContext,
    ) -> tuple[InboundMessageEnvelope, ...]:
        """Normalize every supported Meta message into the canonical envelope."""
        messages: list[InboundMessageEnvelope] = []
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value") or {}
                    for raw_message in value.get("messages", []):
                        message = self._normalize_message(raw_message, route=route)
                        if message is not None:
                            messages.append(message)
        except (
            AttributeError,
            KeyError,
            OSError,
            OverflowError,
            TypeError,
            ValueError,
            ValidationError,
        ) as exc:
            raise WhatsAppInboundPayloadInvalid(
                "Meta message payload is invalid"
            ) from exc
        return tuple(messages)

    @staticmethod
    def _normalize_message(
        message: Mapping[str, Any],
        *,
        route: InboundRouteContext,
    ) -> InboundMessageEnvelope | None:
        provider_type = str(message.get("type", ""))
        content_type = _INBOUND_TYPE_MAP.get(provider_type)
        if content_type is None:
            logger.warning(
                "whatsapp_unknown_message_type",
                extra={"type": provider_type},
            )
            return None

        provider_media_id: str | None = None
        interaction_id: str | None = None
        if provider_type == "interactive":
            interactive = message.get("interactive") or {}
            selection = (
                interactive.get("list_reply") or interactive.get("button_reply") or {}
            )
            interaction_id = selection.get("id") or None
            content = selection.get("title") or selection.get("id") or ""
        elif content_type == InboundContentType.TEXT:
            if provider_type == "location":
                content = "[ubicación]"
            else:
                content = (message.get("text") or {}).get("body", "")
        elif content_type == InboundContentType.AUDIO:
            media = message.get("audio") or message.get("voice") or {}
            provider_media_id = media.get("id")
            content = "[audio]"
        elif content_type == InboundContentType.IMAGE:
            content = (message.get("image") or {}).get("caption") or "[imagen]"
        elif content_type == InboundContentType.VIDEO:
            content = (message.get("video") or {}).get("caption") or "[video]"
        else:
            filename = (message.get("document") or {}).get("filename", "")
            content = f"[archivo: {filename}]" if filename else "[archivo]"

        sender_id = message["from"]
        reply_message_id = (message.get("context") or {}).get("id")
        timestamp = datetime.fromtimestamp(
            int(message["timestamp"]),
            tz=timezone.utc,
        )
        return InboundMessageEnvelope(
            correlation_id=uuid4(),
            channel="whatsapp",
            route=route,
            provider_message_id=message["id"],
            provider_thread_id=sender_id,
            provider_sender_id=sender_id,
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            reply_context=(
                InboundReplyContext(provider_message_id=reply_message_id)
                if reply_message_id
                else None
            ),
            provider_media_id=provider_media_id,
            interaction_id=interaction_id,
        )

    def parse_statuses(self, payload: dict) -> list[dict]:
        """
        Extrae los eventos de status de entrega de un payload de Meta.

        Meta manda estos callbacks (en el array `statuses`, no `messages`) para
        informar el ciclo de vida real del mensaje saliente: sent → delivered →
        read, o failed (con un código de error). Antes se descartaban; ahora los
        parseamos para tener visibilidad real de entrega.

        Retorna una lista de dicts (vacía si el payload no trae statuses):
          {message_id, recipient, status, timestamp, error_code, error_title}
        """
        out: list[dict] = []
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for st in value.get("statuses", []):
                        err = (st.get("errors") or [{}])[0]
                        code = err.get("code")
                        out.append(
                            {
                                "message_id": st.get("id"),
                                "recipient": st.get("recipient_id"),
                                "status": st.get("status"),
                                "timestamp": st.get("timestamp"),
                                "error_code": str(code) if code is not None else None,
                                "error_title": err.get("title") or err.get("message"),
                            }
                        )
        except (KeyError, IndexError, TypeError) as e:
            logger.error("whatsapp_parse_statuses_error", extra={"error": str(e)})
        return out

    async def mark_as_read(
        self,
        message_id: str,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> None:
        """
        Marca el mensaje del usuario como leído (doble ✓ azul).
        Se envía al inicio del pipeline para señalar al usuario que el mensaje
        fue recibido y se está procesando, reduciendo la percepción de latencia.
        Falla silenciosamente — no es crítico para el flujo.
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            return
        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            async with whatsapp_semaphore, httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, headers=headers, json=body)
        except Exception:
            pass  # silencioso — no bloquea el pipeline

    async def show_typing(
        self,
        message_id: str,
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> None:
        """
        Envía indicador de escritura ("escribiendo...") al usuario.
        Meta Cloud API requiere el message_id del último mensaje recibido.
        Dura ~25 segundos o hasta que se envíe un mensaje real.
        Falla silenciosamente — es una mejora de UX, no bloquea el pipeline.

        Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/typing-indicators
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            return
        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        }
        try:
            async with whatsapp_semaphore, httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, headers=headers, json=body)
        except Exception:
            pass  # silencioso


whatsapp_service = WhatsAppService()
