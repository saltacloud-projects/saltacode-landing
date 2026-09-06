"""Code-owned channel adapter catalog and evidence-based readiness projection."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.channel_inbound import ChannelInboundJob
from app.models.outbound import OutboundMessage
from app.models.platform import ChatConversation, ChatMessage


@dataclass(frozen=True)
class ChannelAdapterSpec:
    adapter_key: str
    channel: str
    implementation_status: str
    capabilities: tuple[str, ...]
    credentials_required: bool
    version: int = 1
    blocking_codes: tuple[str, ...] = ()

    @property
    def is_implemented(self) -> bool:
        return self.implementation_status == "implemented"


@dataclass(frozen=True)
class ChannelConnectionReadiness:
    connection: ChannelConnection
    readiness: str
    adapter_implemented: bool
    settings_valid: bool
    credentials_state: str
    routing_state: str
    active_route_count: int
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    blocking_codes: tuple[str, ...]


class ChannelCatalogError(ValueError):
    """Base error for invalid adapter or channel configuration."""


class ChannelAdapterUnavailable(ChannelCatalogError):
    """The requested adapter exists in the catalog but has no implementation."""


class ChannelVersionConflict(ChannelCatalogError):
    """A persisted connection or route changed after the caller read it."""


CHANNEL_ADAPTERS: tuple[ChannelAdapterSpec, ...] = (
    ChannelAdapterSpec(
        adapter_key="web_builtin",
        channel="web",
        implementation_status="implemented",
        capabilities=("inbound_text", "outbound_text", "resumable_stream"),
        credentials_required=False,
    ),
    ChannelAdapterSpec(
        adapter_key="meta_whatsapp_cloud",
        channel="whatsapp",
        implementation_status="implemented",
        capabilities=(
            "inbound_text",
            "inbound_media",
            "outbound_text",
            "outbound_media",
            "delivery_receipts",
        ),
        credentials_required=True,
    ),
    ChannelAdapterSpec(
        adapter_key="email",
        channel="email",
        implementation_status="planned",
        capabilities=("inbound_text", "outbound_text"),
        credentials_required=True,
        blocking_codes=("provider_required",),
    ),
    ChannelAdapterSpec(
        adapter_key="meta_instagram_graph",
        channel="instagram_dm",
        implementation_status="planned",
        capabilities=("inbound_text", "outbound_text"),
        credentials_required=True,
        blocking_codes=("blocked_external",),
    ),
    ChannelAdapterSpec(
        adapter_key="meta_messenger_graph",
        channel="facebook_messenger",
        implementation_status="planned",
        capabilities=("inbound_text", "outbound_text"),
        credentials_required=True,
        blocking_codes=("blocked_external",),
    ),
)

_ADAPTERS_BY_KEY = {adapter.adapter_key: adapter for adapter in CHANNEL_ADAPTERS}
_ADAPTERS_BY_CHANNEL = {adapter.channel: adapter for adapter in CHANNEL_ADAPTERS}
_META_ACCOUNT_PATTERN = re.compile(r"^[0-9]{1,64}$")


def resolve_channel_adapter(
    *,
    channel: str,
    adapter_key: str | None = None,
) -> ChannelAdapterSpec:
    """Resolve an explicit or canonical adapter without accepting mutable capabilities."""

    adapter = (
        _ADAPTERS_BY_KEY.get(adapter_key)
        if adapter_key is not None
        else _ADAPTERS_BY_CHANNEL.get(channel)
    )
    if adapter is None:
        raise ChannelCatalogError("channel_adapter_unknown")
    if adapter.channel != channel:
        raise ChannelCatalogError("channel_adapter_mismatch")
    return adapter


def require_implemented_adapter(
    *,
    channel: str,
    adapter_key: str | None = None,
) -> ChannelAdapterSpec:
    adapter = resolve_channel_adapter(channel=channel, adapter_key=adapter_key)
    if not adapter.is_implemented:
        raise ChannelAdapterUnavailable("channel_adapter_not_implemented")
    return adapter


def require_version(*, current: int, expected: int, resource: str) -> None:
    if current != expected:
        raise ChannelVersionConflict(f"{resource}_version_conflict")


class ChannelCatalogService:
    """Build readiness from persisted configuration and durable traffic evidence."""

    async def list_readiness(
        self,
        db: AsyncSession,
    ) -> list[ChannelConnectionReadiness]:
        connections = (
            (
                await db.execute(
                    select(ChannelConnection).order_by(ChannelConnection.name)
                )
            )
            .scalars()
            .all()
        )
        routes = (await db.execute(select(ChannelAgentRoute))).scalars().all()
        routes_by_connection: dict[uuid.UUID, list[ChannelAgentRoute]] = {}
        for route in routes:
            routes_by_connection.setdefault(route.channel_connection_id, []).append(
                route
            )

        web_inbound = await self._web_inbound_evidence(db)
        external_inbound = await self._external_inbound_evidence(db)
        whatsapp_outbound = await self._whatsapp_outbound_evidence(db)

        return [
            self._connection_readiness(
                connection,
                routes_by_connection.get(connection.id, []),
                last_inbound_at=(
                    web_inbound.get(connection.id)
                    if connection.channel == "web"
                    else external_inbound.get(connection.id)
                ),
                last_outbound_at=(
                    whatsapp_outbound.get(connection.id)
                    if connection.channel == "whatsapp"
                    else None
                ),
            )
            for connection in connections
        ]

    @staticmethod
    async def _web_inbound_evidence(
        db: AsyncSession,
    ) -> dict[uuid.UUID, datetime]:
        rows = (
            await db.execute(
                select(
                    ChannelAgentRoute.channel_connection_id,
                    func.max(ChatMessage.created_at),
                )
                .join(
                    ChatConversation,
                    ChatConversation.channel_route_id == ChannelAgentRoute.id,
                )
                .join(
                    ChatMessage,
                    ChatMessage.conversation_id == ChatConversation.id,
                )
                .where(
                    ChannelAgentRoute.channel == "web",
                    ChatMessage.role == "user",
                )
                .group_by(ChannelAgentRoute.channel_connection_id)
            )
        ).all()
        return {connection_id: occurred_at for connection_id, occurred_at in rows}

    @staticmethod
    async def _external_inbound_evidence(
        db: AsyncSession,
    ) -> dict[uuid.UUID, datetime]:
        rows = (
            await db.execute(
                select(
                    ChannelInboundJob.channel_connection_id,
                    func.max(ChannelInboundJob.created_at),
                ).group_by(ChannelInboundJob.channel_connection_id)
            )
        ).all()
        return {connection_id: occurred_at for connection_id, occurred_at in rows}

    @staticmethod
    async def _whatsapp_outbound_evidence(
        db: AsyncSession,
    ) -> dict[uuid.UUID, datetime]:
        rows = (
            await db.execute(
                select(
                    ChannelAgentRoute.channel_connection_id,
                    func.max(
                        func.coalesce(
                            OutboundMessage.delivered_at,
                            OutboundMessage.accepted_at,
                        )
                    ),
                )
                .join(
                    OutboundMessage,
                    OutboundMessage.channel_route_id == ChannelAgentRoute.id,
                )
                .where(
                    ChannelAgentRoute.channel == "whatsapp",
                    (
                        OutboundMessage.delivered_at.is_not(None)
                        | OutboundMessage.accepted_at.is_not(None)
                    ),
                )
                .group_by(ChannelAgentRoute.channel_connection_id)
            )
        ).all()
        return {connection_id: occurred_at for connection_id, occurred_at in rows}

    @staticmethod
    def _connection_readiness(
        connection: ChannelConnection,
        routes: list[ChannelAgentRoute],
        *,
        last_inbound_at: datetime | None,
        last_outbound_at: datetime | None,
    ) -> ChannelConnectionReadiness:
        adapter = resolve_channel_adapter(
            channel=connection.channel,
            adapter_key=connection.adapter_key,
        )
        settings_valid = ChannelCatalogService._settings_are_valid(
            connection,
            adapter,
        )
        credentials_state = (
            "not_required"
            if not adapter.credentials_required
            else (
                "stored_unverified" if connection.encrypted_credentials else "missing"
            )
        )
        route_inconsistent = any(
            route.channel != connection.channel
            or route.channel_connection_id != connection.id
            for route in routes
        )
        active_route_count = sum(route.is_active for route in routes)
        if route_inconsistent:
            routing_state = "inconsistent"
        elif active_route_count:
            routing_state = "active"
        elif routes:
            routing_state = "inactive"
        else:
            routing_state = "not_configured"

        blocking_codes = list(adapter.blocking_codes)
        if not adapter.is_implemented:
            blocking_codes.append("adapter_not_implemented")
        if not connection.is_active:
            blocking_codes.append("connection_disabled")
        if not settings_valid:
            blocking_codes.append("settings_invalid")
        if credentials_state == "missing":
            blocking_codes.append("credentials_missing")
        if routing_state == "not_configured":
            blocking_codes.append("route_missing")
        elif routing_state == "inactive":
            blocking_codes.append("route_inactive")
        elif routing_state == "inconsistent":
            blocking_codes.append("route_inconsistent")

        has_traffic = last_inbound_at is not None or last_outbound_at is not None
        configuration_blocked = (
            not settings_valid
            or credentials_state == "missing"
            or routing_state != "active"
        )
        if not adapter.is_implemented:
            readiness = "not_implemented"
        elif not connection.is_active:
            readiness = "disabled"
        elif configuration_blocked and has_traffic:
            readiness = "degraded"
        elif configuration_blocked:
            readiness = "configuration_required"
        elif has_traffic:
            readiness = "traffic_observed"
        else:
            readiness = "configured_unverified"
            blocking_codes.append("traffic_not_observed")

        return ChannelConnectionReadiness(
            connection=connection,
            readiness=readiness,
            adapter_implemented=adapter.is_implemented,
            settings_valid=settings_valid,
            credentials_state=credentials_state,
            routing_state=routing_state,
            active_route_count=active_route_count,
            last_inbound_at=last_inbound_at,
            last_outbound_at=last_outbound_at,
            blocking_codes=tuple(dict.fromkeys(blocking_codes)),
        )

    @staticmethod
    def _settings_are_valid(
        connection: ChannelConnection,
        adapter: ChannelAdapterSpec,
    ) -> bool:
        if not isinstance(connection.settings_json, dict):
            return False
        if adapter.adapter_key == "meta_whatsapp_cloud":
            return bool(
                connection.external_account_id
                and _META_ACCOUNT_PATTERN.fullmatch(
                    connection.external_account_id.strip()
                )
            )
        return True


channel_catalog_service = ChannelCatalogService()
