"""Application boundary for persisted agent runtime and deterministic routing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import (
    AgentRuntimeConfig,
    ChannelAgentRoute,
    ChannelConnection,
    ProviderConnection,
)
from app.services.credentials import (
    CredentialDecryptError,
    CredentialStoreUnavailable,
    credential_cipher,
)


class AgentRuntimeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedAgentRuntime:
    profile: AgentProfile
    config: AgentRuntimeConfig
    provider: ProviderConnection
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class ResolvedAgentRoute:
    route: ChannelAgentRoute
    connection: ChannelConnection
    runtime: ResolvedAgentRuntime


class ConnectionService:
    async def create_provider(self, db, data, *, actor: str):
        row = ProviderConnection(
            **data.model_dump(exclude={"credentials", "settings"}),
            settings_json=data.settings,
            created_by=actor,
            updated_by=actor,
        )
        if data.credentials is not None:
            row.encrypted_credentials = credential_cipher.encrypt(
                data.credentials.model_dump()
            )
        db.add(row)
        await db.flush()
        return row

    async def update_provider(self, db, row, data, *, actor: str):
        values = data.model_dump(
            exclude_none=True, exclude={"credentials", "clear_credentials", "settings"}
        )
        for key, value in values.items():
            setattr(row, key, value)
        if data.settings is not None:
            row.settings_json = data.settings
        if data.clear_credentials:
            row.encrypted_credentials = None
        elif data.credentials is not None:
            row.encrypted_credentials = credential_cipher.encrypt(
                data.credentials.model_dump()
            )
        row.updated_by = actor
        await db.flush()
        return row

    async def create_channel(self, db, data, *, actor: str):
        row = ChannelConnection(
            **data.model_dump(exclude={"credentials", "settings"}),
            settings_json=data.settings,
            created_by=actor,
            updated_by=actor,
        )
        if data.credentials is not None:
            row.encrypted_credentials = credential_cipher.encrypt(
                data.credentials.model_dump()
            )
        db.add(row)
        await db.flush()
        return row

    async def update_channel(self, db, row, data, *, actor: str):
        values = data.model_dump(
            exclude_none=True, exclude={"credentials", "clear_credentials", "settings"}
        )
        for key, value in values.items():
            setattr(row, key, value)
        if data.settings is not None:
            row.settings_json = data.settings
        if data.clear_credentials:
            row.encrypted_credentials = None
        elif data.credentials is not None:
            if row.channel != "whatsapp":
                raise ValueError("web connections do not accept credentials")
            row.encrypted_credentials = credential_cipher.encrypt(
                data.credentials.model_dump()
            )
        row.updated_by = actor
        await db.flush()
        return row


class AgentRuntimeResolver:
    async def resolve_agent(
        self,
        db: AsyncSession,
        agent_id: uuid.UUID | str,
        *,
        allow_inactive: bool = False,
        require_public: bool = False,
    ) -> ResolvedAgentRuntime:
        try:
            parsed_id = (
                agent_id if isinstance(agent_id, uuid.UUID) else uuid.UUID(agent_id)
            )
        except (TypeError, ValueError) as exc:
            raise AgentRuntimeUnavailable("agent is unknown") from exc
        row = (
            await db.execute(
                select(AgentProfile, AgentRuntimeConfig, ProviderConnection)
                .join(
                    AgentRuntimeConfig, AgentRuntimeConfig.agent_id == AgentProfile.id
                )
                .join(
                    ProviderConnection,
                    ProviderConnection.id == AgentRuntimeConfig.provider_connection_id,
                )
                .where(AgentProfile.id == parsed_id)
            )
        ).one_or_none()
        if row is None:
            raise AgentRuntimeUnavailable("agent runtime is not configured")
        profile, config, provider = row
        if not allow_inactive and not profile.is_active:
            raise AgentRuntimeUnavailable("agent is inactive")
        if require_public and not profile.is_public:
            raise AgentRuntimeUnavailable("agent is not public")
        if not provider.is_active:
            raise AgentRuntimeUnavailable("provider connection is inactive")
        try:
            credentials = credential_cipher.decrypt(provider.encrypted_credentials)
        except (CredentialDecryptError, CredentialStoreUnavailable) as exc:
            raise AgentRuntimeUnavailable(
                "provider credentials are unavailable"
            ) from exc
        api_key = credentials.get("api_key", "")
        if not api_key:
            raise AgentRuntimeUnavailable("provider credentials are unavailable")
        return ResolvedAgentRuntime(profile, config, provider, api_key)

    async def resolve_route(
        self,
        db: AsyncSession,
        channel: str,
        route_key: str,
        *,
        require_public: bool = False,
    ) -> ResolvedAgentRoute:
        row = (
            await db.execute(
                select(ChannelAgentRoute, ChannelConnection)
                .join(
                    ChannelConnection,
                    ChannelConnection.id == ChannelAgentRoute.channel_connection_id,
                )
                .where(
                    ChannelAgentRoute.channel == channel,
                    ChannelAgentRoute.route_key == route_key,
                    ChannelAgentRoute.is_active == True,  # noqa: E712
                    ChannelConnection.is_active == True,  # noqa: E712
                )
            )
        ).one_or_none()
        if row is None:
            raise AgentRuntimeUnavailable("channel route is unavailable")
        route, connection = row
        if connection.channel != route.channel:
            raise AgentRuntimeUnavailable("channel route is inconsistent")
        runtime = await self.resolve_agent(
            db, route.agent_id, allow_inactive=False, require_public=require_public
        )
        return ResolvedAgentRoute(route, connection, runtime)


connection_service = ConnectionService()
agent_runtime_resolver = AgentRuntimeResolver()
