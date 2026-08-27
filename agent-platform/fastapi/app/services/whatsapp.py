"""
Agent Platform — WhatsAppService
Integración con Meta Cloud API (WhatsApp Business).

Responsabilidades:
  - Verificar el webhook al configurarlo en Meta (GET challenge)
  - Parsear mensajes entrantes del payload de Meta (POST)
  - Enviar mensajes de texto al usuario vía Graph API

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.config import settings
from app.core.concurrency import whatsapp_semaphore
from app.models.agent_runtime import ChannelConnection
from app.schemas.agent_runtime import WhatsAppCredentials
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


class WhatsAppConnectionUnavailable(RuntimeError):
    """Raised when a persisted WhatsApp connection cannot be used safely."""


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


class WhatsAppService:
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

    def parse_inbound(self, payload: dict) -> dict | None:
        """
        Extrae phone_number, content, message_id e input_type de un payload de Meta.
        Retorna None solo si no es un mensaje real (status updates, reactions, etc.).

        input_type canónicos:
          text     → mensaje de texto normal
          audio    → nota de voz o audio
          image    → imagen / foto
          video    → video
          file     → documento adjunto (PDF, Excel, etc.)
          sticker  → sticker (se trata como imagen no soportada)
          location → ubicación compartida
        """
        # Mapeo de tipos Meta → input_type canónico interno
        TYPE_MAP = {
            "text": "text",
            "interactive": "text",  # selección de menú interactivo → se trata como texto
            "audio": "audio",
            "voice": "audio",
            "image": "image",
            "video": "video",
            "document": "file",
            "sticker": "image",
            "location": "text",  # podría ser útil en el futuro
        }

        try:
            entry = payload.get("entry", [{}])[0]
            change = entry.get("changes", [{}])[0].get("value", {})
            messages = change.get("messages", [])
            if not messages:
                return None  # status update, delivery receipt, etc.

            msg = messages[0]
            msg_type = msg.get("type", "")
            input_type = TYPE_MAP.get(msg_type)

            if input_type is None:
                # Tipo desconocido — ignorar silenciosamente
                logger.warning(
                    "whatsapp_unknown_message_type", extra={"type": msg_type}
                )
                return None

            # Extraer content y media_id según el tipo
            audio_media_id: str | None = None
            interactive_id: str | None = None

            if msg_type == "interactive":
                # El usuario tocó una opción del menú interactivo.
                # Preservamos el `id` (estable, definido por la app) además del
                # `title` (lo que el usuario ve). El id permite enrutar
                # determinísticamente en el pipeline sin depender del LLM.
                interactive = msg.get("interactive", {})
                list_reply = (
                    interactive.get("list_reply")
                    or interactive.get("button_reply")
                    or {}
                )
                interactive_id = list_reply.get("id") or None
                # Usamos el título como contenido — es lo que el usuario "dijo"
                content = list_reply.get("title", "")
                if not content:
                    content = list_reply.get("id", "")
            elif input_type == "text":
                content = msg.get("text", {}).get("body", "")
            elif input_type == "audio":
                audio_data = msg.get("audio") or msg.get("voice") or {}
                audio_media_id = audio_data.get("id")
                content = "[audio]"  # placeholder, el pipeline lo reemplazará con la transcripción
            elif input_type == "image":
                content = msg.get("image", {}).get("caption", "[imagen]") or "[imagen]"
            elif input_type == "video":
                content = msg.get("video", {}).get("caption", "[video]") or "[video]"
            elif input_type == "file":
                filename = msg.get("document", {}).get("filename", "")
                content = f"[archivo: {filename}]" if filename else "[archivo]"
            else:
                content = f"[{msg_type}]"

            # Mensaje citado (reply): Meta manda `context.id` con el wamid del
            # mensaje al que el usuario respondió. Lo usamos para resolver el
            # referente ("¿cómo obtuviste este dato?") contra el texto que enviamos.
            quoted_id = (msg.get("context") or {}).get("id")

            return {
                "phone_number": msg["from"],
                "content": content,
                "message_id": msg["id"],
                "timestamp": msg.get("timestamp", ""),
                "input_type": input_type,
                "audio_media_id": audio_media_id,  # None si no es audio
                "interactive_id": interactive_id,  # None salvo en menus/botones
                "quoted_id": quoted_id,  # None salvo en respuestas citadas
            }

        except (KeyError, IndexError, TypeError) as e:
            logger.error("whatsapp_parse_error", extra={"error": str(e)})
            return None

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

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """
        Normaliza números de WhatsApp para el envío via Cloud API.

        Argentina (y Brasil) tienen un prefijo móvil '9' que WhatsApp agrega
        automáticamente en el campo 'from' de los webhooks, pero la Cloud API
        requiere el número SIN ese 9 al enviar:
          - Webhook from:  549XXXXXXXXXX  (con 9)
          - Cloud API to:  54XXXXXXXXXX   (sin 9)

        Meta hace la conversión internamente y devuelve wa_id con el 9.
        """
        # Argentina móvil: 549 + 10 dígitos = 13 chars → quitar el 9
        if phone.startswith("549") and len(phone) == 13:
            return "54" + phone[3:]
        # Brasil móvil: 559 + 11 dígitos = 14 chars → quitar el 9
        if phone.startswith("559") and len(phone) == 14:
            return "55" + phone[3:]
        return phone

    async def upload_media(
        self,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> str | None:
        """
        Sube un archivo al media storage de WhatsApp Business Cloud API.
        Retorna el media_id si fue exitoso, None si falló.
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            logger.warning(
                "whatsapp_send_skipped",
                extra={
                    "reason": "credenciales no configuradas",
                    "request_id": request_id,
                },
            )
            return None

        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {delivery.access_token}"}
        async with whatsapp_semaphore, httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    url,
                    headers=headers,
                    data={"messaging_product": "whatsapp", "type": mime_type},
                    files={"file": (filename, file_bytes, mime_type)},
                )
                resp.raise_for_status()
                media_id = resp.json().get("id")
                logger.info(
                    "whatsapp_media_uploaded",
                    extra={
                        "media_id": media_id,
                        "file_name": filename,
                        "bytes": len(file_bytes),
                        "request_id": request_id,
                    },
                )
                return media_id
            except httpx.HTTPStatusError as e:
                logger.error(
                    "whatsapp_media_upload_error",
                    extra={
                        "status": e.response.status_code,
                        "request_id": request_id,
                    },
                )
                return None
            except Exception as e:
                logger.error(
                    "whatsapp_media_upload_error",
                    extra={"error": str(e), "request_id": request_id},
                )
                return None

    async def upload_media_path(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> str | None:
        """Sube un archivo persistido usando streaming multipart."""
        delivery = self._delivery_context(connection)
        if delivery is None:
            logger.warning(
                "whatsapp_send_skipped",
                extra={
                    "reason": "credenciales no configuradas",
                    "request_id": request_id,
                },
            )
            return None
        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {delivery.access_token}"}
        try:
            with file_path.open("rb") as file_handle:
                async with (
                    whatsapp_semaphore,
                    httpx.AsyncClient(timeout=120.0) as client,
                ):
                    resp = await client.post(
                        url,
                        headers=headers,
                        data={"messaging_product": "whatsapp", "type": mime_type},
                        files={"file": (filename, file_handle, mime_type)},
                    )
                    resp.raise_for_status()
                    media_id = resp.json().get("id")
            logger.info(
                "whatsapp_media_uploaded",
                extra={
                    "media_id": media_id,
                    "file_name": filename,
                    "bytes": file_path.stat().st_size,
                    "request_id": request_id,
                },
            )
            return media_id
        except httpx.HTTPStatusError as exc:
            logger.error(
                "whatsapp_media_upload_error",
                extra={"status": exc.response.status_code, "request_id": request_id},
            )
            return None
        except Exception as exc:
            logger.error(
                "whatsapp_media_upload_error",
                extra={"error_type": type(exc).__name__, "request_id": request_id},
            )
            return None

    async def send_document_message(
        self,
        phone: str,
        media_id: str,
        filename: str,
        caption: str = "",
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> bool:
        """
        Envía un documento (archivo) al número indicado via Graph API usando un media_id previamente subido.
        Retorna True si fue exitoso.
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            logger.warning(
                "whatsapp_send_skipped",
                extra={
                    "reason": "credenciales no configuradas",
                    "request_id": request_id,
                },
            )
            return False

        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        normalized_phone = self._normalize_phone(phone)
        doc_payload: dict = {"id": media_id, "filename": filename}
        if caption:
            doc_payload["caption"] = caption
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "document",
            "document": doc_payload,
        }
        async with whatsapp_semaphore, httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                logger.info(
                    "whatsapp_document_sent",
                    extra={
                        "phone": normalized_phone,
                        "file_name": filename,
                        "request_id": request_id,
                    },
                )
                return True
            except httpx.HTTPStatusError as e:
                logger.error(
                    "whatsapp_send_error",
                    extra={
                        "phone": phone,
                        "status": e.response.status_code,
                    },
                )
                return False
            except httpx.RequestError as e:
                logger.error("whatsapp_request_error", extra={"error": str(e)})
                return False

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

    async def send_image_message(
        self,
        phone: str,
        media_id: str,
        caption: str = "",
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> bool:
        """
        Envía una imagen al número indicado via Graph API usando un media_id previamente subido.
        La imagen se muestra inline en el chat (sin necesidad de descargar).
        Retorna True si fue exitoso.
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            return False

        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        normalized_phone = self._normalize_phone(phone)
        img_payload: dict = {"id": media_id}
        if caption:
            img_payload["caption"] = caption
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "image",
            "image": img_payload,
        }
        async with whatsapp_semaphore, httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                logger.info(
                    "whatsapp_image_sent",
                    extra={"phone": normalized_phone, "request_id": request_id},
                )
                return True
            except httpx.HTTPStatusError as e:
                logger.error(
                    "whatsapp_send_error",
                    extra={
                        "phone": phone,
                        "status": e.response.status_code,
                    },
                )
                return False
            except httpx.RequestError as e:
                logger.error("whatsapp_request_error", extra={"error": str(e)})
                return False

    async def send_template_message(
        self,
        phone: str,
        template_name: str,
        language_code: str,
        header_image_id: str | None = None,
        body_params: list[str] | None = None,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> str | None:
        """
        Envía un message template pre-aprobado por Meta.
        Usado para iniciar conversaciones (business-initiated) fuera de la
        ventana de 24h, por ejemplo para push de reportes programados.

        Args:
            phone: Número destino (formato 549XXXXXXXXXX)
            template_name: Nombre del template aprobado (ej: 'reporte_diario_compras')
            language_code: Código de idioma (ej: 'es_AR')
            header_image_id: media_id de la imagen del header (si aplica)
            body_params: Lista de valores para {{1}}, {{2}}, etc.
            request_id: ID para logging

        Retorna el message_id (wamid...) que devuelve Meta si el envío fue aceptado
        (HTTP 200), o None si falló. OJO: "aceptado" no es "entregado" — la entrega
        real se confirma luego por webhook de status (ver delivery_status.py).

        Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            return None

        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        normalized_phone = self._normalize_phone(phone)

        # Construir los componentes del template
        components: list[dict] = []

        # Header con imagen (si aplica)
        if header_image_id:
            components.append(
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"id": header_image_id}}],
                }
            )

        # Body con parámetros posicionales
        if body_params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in body_params],
                }
            )

        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }

        async with whatsapp_semaphore, httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                message_id = (data.get("messages") or [{}])[0].get("id")
                logger.info(
                    "whatsapp_template_sent",
                    extra={
                        "phone": normalized_phone,
                        "template": template_name,
                        "message_id": message_id,
                        "request_id": request_id,
                    },
                )
                return message_id
            except httpx.HTTPStatusError as e:
                logger.error(
                    "whatsapp_template_send_error",
                    extra={
                        "phone": phone,
                        "template": template_name,
                        "status": e.response.status_code,
                        "request_id": request_id,
                    },
                )
                return None
            except httpx.RequestError as e:
                logger.error("whatsapp_request_error", extra={"error": str(e)})
                return None

    async def send_text_message(
        self,
        phone: str,
        text: str,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> str | None:
        """
        Envía un mensaje de texto al número indicado via Graph API.
        Retorna el message_id (wamid...) que asigna Meta si fue aceptado, o None si
        falló o si WhatsApp está deshabilitado. El wamid permite correlacionar las
        respuestas citadas del usuario con el mensaje al que responden.
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            logger.warning(
                "whatsapp_send_skipped",
                extra={
                    "reason": "credenciales no configuradas",
                    "request_id": request_id,
                },
            )
            return None

        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        normalized_phone = self._normalize_phone(phone)
        text = sanitize_whatsapp_text(text)
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }

        async with whatsapp_semaphore, httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                message_id = (data.get("messages") or [{}])[0].get("id")
                logger.info(
                    "whatsapp_message_sent",
                    extra={
                        "phone": normalized_phone,
                        "original_phone": phone,
                        "request_id": request_id,
                        "status": resp.status_code,
                        "message_id": message_id,
                    },
                )
                return message_id
            except httpx.HTTPStatusError as e:
                logger.error(
                    "whatsapp_send_error",
                    extra={
                        "phone": phone,
                        "status": e.response.status_code,
                    },
                )
                return None
            except httpx.RequestError as e:
                logger.error("whatsapp_request_error", extra={"error": str(e)})
                return None

    async def send_reply_buttons(
        self,
        phone: str,
        body_text: str,
        buttons: list[dict],
        footer_text: str | None = None,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> bool:
        """
        Envía un mensaje con botones de respuesta rápida (máx 3 botones).
        Cuando el usuario toca un botón, el título se envía como mensaje interactivo.

        Args:
            phone: Número destino
            body_text: Texto principal del mensaje
            buttons: Lista de dicts con 'id' y 'title' (máx 20 chars c/u)
            footer_text: Footer opcional
            request_id: ID para logging

        Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-reply-buttons
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            return False

        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        normalized_phone = self._normalize_phone(phone)

        interactive: dict = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": b["id"], "title": b["title"][:20]},
                    }
                    for b in buttons[:3]  # WhatsApp permite máx 3 botones
                ],
            },
        }
        if footer_text:
            interactive["footer"] = {"text": footer_text}

        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "interactive",
            "interactive": interactive,
        }

        async with whatsapp_semaphore, httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                logger.info(
                    "whatsapp_reply_buttons_sent",
                    extra={
                        "phone": normalized_phone,
                        "buttons": len(buttons),
                        "request_id": request_id,
                    },
                )
                return True
            except httpx.HTTPStatusError as e:
                logger.error(
                    "whatsapp_reply_buttons_error",
                    extra={
                        "phone": phone,
                        "status": e.response.status_code,
                        "request_id": request_id,
                    },
                )
                return False
            except httpx.RequestError as e:
                logger.error("whatsapp_request_error", extra={"error": str(e)})
                return False

    async def send_interactive_list(
        self,
        phone: str,
        body_text: str,
        button_text: str,
        sections: list[dict],
        header_text: str | None = None,
        footer_text: str | None = None,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> bool:
        """
        Envía un mensaje interactivo tipo 'list' de WhatsApp.
        Permite mostrar un menú con secciones y opciones que el usuario toca para elegir.

        Args:
            phone: Número de teléfono destino
            body_text: Texto principal del mensaje
            button_text: Texto del botón que abre la lista (máx 20 chars)
            sections: Lista de secciones, cada una con 'title' y 'rows'.
                      Cada row tiene 'id', 'title' (máx 24 chars) y 'description' (máx 72 chars).
            header_text: Texto del header (opcional)
            footer_text: Texto del footer (opcional)
            request_id: ID de request para logging

        Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-list-messages
        """
        delivery = self._delivery_context(connection)
        if delivery is None:
            logger.warning(
                "whatsapp_send_skipped",
                extra={
                    "reason": "credenciales no configuradas",
                    "request_id": request_id,
                },
            )
            return False

        url = f"{GRAPH_API_BASE}/{delivery.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        normalized_phone = self._normalize_phone(phone)

        interactive: dict = {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": button_text[:20],
                "sections": sections,
            },
        }
        if header_text:
            interactive["header"] = {"type": "text", "text": header_text}
        if footer_text:
            interactive["footer"] = {"text": footer_text}

        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalized_phone,
            "type": "interactive",
            "interactive": interactive,
        }

        async with whatsapp_semaphore, httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                logger.info(
                    "whatsapp_interactive_sent",
                    extra={
                        "phone": normalized_phone,
                        "sections": len(sections),
                        "request_id": request_id,
                    },
                )
                return True
            except httpx.HTTPStatusError as e:
                logger.error(
                    "whatsapp_interactive_error",
                    extra={
                        "phone": phone,
                        "status": e.response.status_code,
                        "request_id": request_id,
                    },
                )
                return False
            except httpx.RequestError as e:
                logger.error("whatsapp_request_error", extra={"error": str(e)})
                return False


whatsapp_service = WhatsAppService()
