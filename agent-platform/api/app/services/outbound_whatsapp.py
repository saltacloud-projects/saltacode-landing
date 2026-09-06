"""WhatsApp adapter for frozen outbound commands."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from app.core.concurrency import whatsapp_semaphore
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import OutboundMessage
from app.ports.outbound import Accepted, OutboundResult, Rejected, Unknown
from app.services.rag.storage import StorageError, document_storage
from app.services.whatsapp import (
    GRAPH_API_BASE,
    WhatsAppConnectionUnavailable,
    sanitize_whatsapp_text,
    whatsapp_service,
)


class WhatsAppOutboundAdapter:
    """Translate neutral commands into the persisted WhatsApp route."""

    adapter_key = "meta_whatsapp_cloud"
    _provider_account_pattern = re.compile(r"^[0-9]{1,64}$")
    _recipient_pattern = re.compile(r"^[1-9][0-9]{5,20}$")

    async def deliver(
        self,
        *,
        message: OutboundMessage,
        route: ChannelAgentRoute,
        connection: ChannelConnection,
    ) -> OutboundResult:
        if not self._owns_route(message, route, connection):
            return Rejected("route_unavailable")
        try:
            delivery = whatsapp_service.resolve_connection(
                connection,
                route_key=route.route_key,
            )
        except WhatsAppConnectionUnavailable:
            return Rejected("connection_unavailable")
        if not self._provider_account_pattern.fullmatch(delivery.phone_number_id):
            return Rejected("connection_unavailable")

        headers = {
            "Authorization": f"Bearer {delivery.access_token}",
            "Content-Type": "application/json",
        }
        recipient = self._normalize_recipient(message.destination)
        if not self._recipient_pattern.fullmatch(recipient):
            return Rejected("recipient_invalid")
        if message.kind == "text":
            body = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": sanitize_whatsapp_text(message.payload_json["text"]),
                },
            }
            return await self._post_message(
                delivery.phone_number_id,
                headers=headers,
                body=body,
            )
        if message.kind in {"image", "document"}:
            return await self._deliver_file(
                message,
                phone_number_id=delivery.phone_number_id,
                recipient=recipient,
                access_token=delivery.access_token,
            )
        return Rejected("unsupported_kind")

    async def _deliver_file(
        self,
        message: OutboundMessage,
        *,
        phone_number_id: str,
        recipient: str,
        access_token: str,
    ) -> OutboundResult:
        payload = message.payload_json
        try:
            path = document_storage.path_for(payload["storage_key"])
        except (KeyError, StorageError, TypeError):
            return Rejected("storage_reference_invalid")
        if not path.is_file():
            return Rejected("storage_file_missing")

        upload = await self._upload_file(
            phone_number_id,
            access_token=access_token,
            path=path,
            name=payload["name"],
            mime=payload["mime"],
        )
        if not isinstance(upload, Accepted):
            return upload

        media_payload = {"id": upload.provider_message_id}
        caption = payload.get("caption")
        if caption:
            media_payload["caption"] = caption
        if message.kind == "document":
            media_payload["filename"] = payload["name"]
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": message.kind,
            message.kind: media_payload,
        }
        return await self._post_message(
            phone_number_id,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            body=body,
        )

    async def _upload_file(
        self,
        phone_number_id: str,
        *,
        access_token: str,
        path: Path,
        name: str,
        mime: str,
    ) -> OutboundResult:
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            with path.open("rb") as file_handle:
                async with (
                    whatsapp_semaphore,
                    httpx.AsyncClient(
                        timeout=httpx.Timeout(30.0, connect=5.0)
                    ) as client,
                ):
                    response = await client.post(
                        f"{GRAPH_API_BASE}/{phone_number_id}/media",
                        headers=headers,
                        data={"messaging_product": "whatsapp", "type": mime},
                        files={"file": (name, file_handle, mime)},
                    )
        except httpx.TimeoutException:
            return Unknown("provider_timeout")
        except httpx.RequestError:
            return Unknown("provider_transport_error")
        except OSError:
            return Rejected("storage_file_unreadable")
        return self._classify_response(response, identifier_field="id")

    async def _post_message(
        self,
        phone_number_id: str,
        *,
        headers: dict[str, str],
        body: dict,
    ) -> OutboundResult:
        try:
            async with (
                whatsapp_semaphore,
                httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client,
            ):
                response = await client.post(
                    f"{GRAPH_API_BASE}/{phone_number_id}/messages",
                    headers=headers,
                    json=body,
                )
        except httpx.TimeoutException:
            return Unknown("provider_timeout")
        except httpx.RequestError:
            return Unknown("provider_transport_error")
        return self._classify_response(response, identifier_field="messages")

    @staticmethod
    def _classify_response(
        response: httpx.Response,
        *,
        identifier_field: str,
    ) -> OutboundResult:
        if 400 <= response.status_code < 500:
            return Rejected(f"provider_http_{response.status_code}")
        if not 200 <= response.status_code < 300:
            return Unknown(f"provider_http_{response.status_code}")
        try:
            data = response.json()
            if identifier_field == "messages":
                provider_id = (data.get("messages") or [{}])[0].get("id")
            else:
                provider_id = data.get(identifier_field)
        except (AttributeError, IndexError, TypeError, ValueError):
            return Unknown("provider_response_invalid")
        if not isinstance(provider_id, str) or not provider_id.strip():
            return Unknown("provider_id_missing")
        if len(provider_id.strip()) > 255:
            return Unknown("provider_id_invalid")
        return Accepted(provider_id.strip())

    @classmethod
    def _owns_route(
        cls,
        message: OutboundMessage,
        route: ChannelAgentRoute,
        connection: ChannelConnection,
    ) -> bool:
        return bool(
            route.id == message.channel_route_id
            and route.agent_id == message.agent_id
            and route.channel == message.channel == "whatsapp"
            and route.channel_connection_id
            == message.channel_connection_id
            == connection.id
            and route.version == message.route_version
            and connection.channel == message.channel
            and connection.adapter_key == message.adapter_key == cls.adapter_key
            and connection.version == message.connection_version
            and route.is_active
            and connection.is_active
        )

    @staticmethod
    def _normalize_recipient(recipient: str) -> str:
        if recipient.startswith("549") and len(recipient) == 13:
            return "54" + recipient[3:]
        if recipient.startswith("559") and len(recipient) == 14:
            return "55" + recipient[3:]
        return recipient


whatsapp_outbound_adapter = WhatsAppOutboundAdapter()
