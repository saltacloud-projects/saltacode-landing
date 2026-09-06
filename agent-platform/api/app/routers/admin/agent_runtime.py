"""Admin APIs for reusable connections, per-agent runtime, and channel routes."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import (
    AgentRuntimeConfig,
    ChannelAgentRoute,
    ChannelConnection,
    ProviderConnection,
)
from app.routers.admin.auth import require_permission
from app.schemas.agent_runtime import (
    AgentRouteCreate,
    AgentRouteOut,
    AgentRouteUpdate,
    AgentRuntimeOut,
    AgentRuntimeUpdate,
    ChannelConnectionCreate,
    ChannelConnectionOut,
    ChannelConnectionUpdate,
    ConnectionTestResult,
    ProviderConnectionCreate,
    ProviderConnectionOut,
    ProviderConnectionUpdate,
)
from app.services.admin_rbac import AdminPermission
from app.services.agent_runtime import connection_service
from app.services.credentials import (
    CredentialDecryptError,
    CredentialStoreUnavailable,
    credential_cipher,
)

router = APIRouter(tags=["admin-agent-runtime"])


def _uuid(value: str, detail: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=detail) from exc


async def _get(db, model, value: str, detail: str):
    row = await db.get(model, _uuid(value, detail))
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    return row


@router.get(
    "/provider-connections",
    response_model=list[ProviderConnectionOut],
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_READ))],
)
async def list_providers(db: AsyncSession = Depends(get_db)):
    rows = (
        (await db.execute(select(ProviderConnection).order_by(ProviderConnection.name)))
        .scalars()
        .all()
    )
    return [ProviderConnectionOut.from_model(row) for row in rows]


@router.post(
    "/provider-connections",
    response_model=ProviderConnectionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE))],
)
async def create_provider(
    data: ProviderConnectionCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE)),
):
    try:
        row = await connection_service.create_provider(db, data, actor=admin.email)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Credential encryption is unavailable"
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Provider connection already exists"
        ) from exc
    return ProviderConnectionOut.from_model(row)


@router.patch(
    "/provider-connections/{connection_id}",
    response_model=ProviderConnectionOut,
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE))],
)
async def update_provider(
    connection_id: str,
    data: ProviderConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE)),
):
    row = await _get(
        db, ProviderConnection, connection_id, "Provider connection not found"
    )
    try:
        await connection_service.update_provider(db, row, data, actor=admin.email)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Credential encryption is unavailable"
        ) from exc
    return ProviderConnectionOut.from_model(row)


@router.post(
    "/provider-connections/{connection_id}/deactivate",
    response_model=ProviderConnectionOut,
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE))],
)
async def deactivate_provider(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE)),
):
    row = await _get(
        db, ProviderConnection, connection_id, "Provider connection not found"
    )
    row.is_active = False
    row.updated_by = admin.email
    return ProviderConnectionOut.from_model(row)


@router.post(
    "/provider-connections/{connection_id}/test",
    response_model=ConnectionTestResult,
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE))],
)
async def test_provider_connection(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = await _get(
        db, ProviderConnection, connection_id, "Provider connection not found"
    )
    started = time.monotonic()
    try:
        credentials = credential_cipher.decrypt(row.encrypted_credentials)
        api_key = credentials.get("api_key")
        if not api_key:
            return ConnectionTestResult(
                ok=False, duration_ms=0, error_code="credentials_unavailable"
            )
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, base_url=row.base_url)
        try:
            await client.models.retrieve(
                str(row.settings_json.get("test_model") or settings.openai_model)
            )
        finally:
            await client.close()
    except (CredentialDecryptError, CredentialStoreUnavailable):
        return ConnectionTestResult(
            ok=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="credentials_unavailable",
        )
    except Exception:
        return ConnectionTestResult(
            ok=False,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="provider_unavailable",
        )
    return ConnectionTestResult(
        ok=True, duration_ms=int((time.monotonic() - started) * 1000)
    )


@router.get(
    "/channel-connections",
    response_model=list[ChannelConnectionOut],
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_READ))],
)
async def list_channels(db: AsyncSession = Depends(get_db)):
    rows = (
        (await db.execute(select(ChannelConnection).order_by(ChannelConnection.name)))
        .scalars()
        .all()
    )
    return [ChannelConnectionOut.from_model(row) for row in rows]


@router.post(
    "/channel-connections",
    response_model=ChannelConnectionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE))],
)
async def create_channel(
    data: ChannelConnectionCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE)),
):
    try:
        row = await connection_service.create_channel(db, data, actor=admin.email)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Credential encryption is unavailable"
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Channel connection already exists"
        ) from exc
    return ChannelConnectionOut.from_model(row)


@router.patch(
    "/channel-connections/{connection_id}",
    response_model=ChannelConnectionOut,
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE))],
)
async def update_channel(
    connection_id: str,
    data: ChannelConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE)),
):
    row = await _get(
        db, ChannelConnection, connection_id, "Channel connection not found"
    )
    try:
        await connection_service.update_channel(db, row, data, actor=admin.email)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Credential encryption is unavailable"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ChannelConnectionOut.from_model(row)


@router.post(
    "/channel-connections/{connection_id}/deactivate",
    response_model=ChannelConnectionOut,
    dependencies=[Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE))],
)
async def deactivate_channel(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.CONNECTIONS_MANAGE)),
):
    row = await _get(
        db, ChannelConnection, connection_id, "Channel connection not found"
    )
    row.is_active = False
    row.updated_by = admin.email
    return ChannelConnectionOut.from_model(row)


async def _profile(db, agent_id: str):
    return await _get(db, AgentProfile, agent_id, "Agent profile not found")


@router.get(
    "/profiles/{agent_id}/runtime",
    response_model=AgentRuntimeOut,
    dependencies=[Depends(require_permission(AdminPermission.RUNTIME_READ))],
)
async def get_runtime(agent_id: str, db: AsyncSession = Depends(get_db)):
    await _profile(db, agent_id)
    row = (
        await db.execute(
            select(AgentRuntimeConfig).where(
                AgentRuntimeConfig.agent_id
                == _uuid(agent_id, "Agent profile not found")
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Agent runtime is not configured")
    provider = (
        await db.get(ProviderConnection, row.provider_connection_id)
        if row.provider_connection_id
        else None
    )
    return AgentRuntimeOut.from_model(
        row,
        provider_ready=bool(
            provider and provider.is_active and provider.encrypted_credentials
        ),
    )


@router.patch(
    "/profiles/{agent_id}/runtime",
    response_model=AgentRuntimeOut,
    dependencies=[Depends(require_permission(AdminPermission.RUNTIME_MANAGE))],
)
async def patch_runtime(
    agent_id: str,
    data: AgentRuntimeUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.RUNTIME_MANAGE)),
):
    profile = await _profile(db, agent_id)
    row = (
        await db.execute(
            select(AgentRuntimeConfig).where(AgentRuntimeConfig.agent_id == profile.id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = AgentRuntimeConfig(
            agent_id=profile.id,
            chat_model=settings.openai_model,
            transcription_model=settings.openai_whisper_model,
            summary_enabled=settings.memory_summary_enabled,
            summary_trigger_messages=settings.memory_summary_trigger_messages,
            summary_max_chars=settings.memory_summary_max_chars,
            created_by=admin.email,
        )
        db.add(row)
    provider_requested = "provider_connection_id" in data.model_fields_set
    values = data.model_dump(
        exclude_none=True,
        exclude={"provider_connection_id"},
    )
    if provider_requested:
        if data.provider_connection_id is None:
            row.provider_connection_id = None
        else:
            provider = await _get(
                db,
                ProviderConnection,
                data.provider_connection_id,
                "Provider connection not found",
            )
            row.provider_connection_id = provider.id
    for key, value in values.items():
        setattr(row, key, value)
    if abs((row.rag_vector_weight + row.rag_lexical_weight) - 1.0) > 1e-6:
        raise HTTPException(
            status_code=422, detail="RAG vector and lexical weights must sum to 1"
        )
    row.updated_by = admin.email
    await db.flush()
    provider = (
        await db.get(ProviderConnection, row.provider_connection_id)
        if row.provider_connection_id
        else None
    )
    return AgentRuntimeOut.from_model(
        row,
        provider_ready=bool(
            provider and provider.is_active and provider.encrypted_credentials
        ),
    )


@router.get(
    "/profiles/{agent_id}/routes",
    response_model=list[AgentRouteOut],
    dependencies=[Depends(require_permission(AdminPermission.RUNTIME_READ))],
)
async def list_routes(agent_id: str, db: AsyncSession = Depends(get_db)):
    profile = await _profile(db, agent_id)
    rows = (
        (
            await db.execute(
                select(ChannelAgentRoute)
                .where(ChannelAgentRoute.agent_id == profile.id)
                .order_by(ChannelAgentRoute.channel, ChannelAgentRoute.route_key)
            )
        )
        .scalars()
        .all()
    )
    return [AgentRouteOut.from_model(row) for row in rows]


@router.post(
    "/profiles/{agent_id}/routes",
    response_model=AgentRouteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(AdminPermission.RUNTIME_MANAGE))],
)
async def create_route(
    agent_id: str,
    data: AgentRouteCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.RUNTIME_MANAGE)),
):
    profile = await _profile(db, agent_id)
    connection = await _get(
        db,
        ChannelConnection,
        data.channel_connection_id,
        "Channel connection not found",
    )
    if connection.channel != data.channel:
        raise HTTPException(
            status_code=422, detail="Route channel must match its connection"
        )
    row = ChannelAgentRoute(
        agent_id=profile.id,
        channel=data.channel,
        route_key=data.route_key,
        channel_connection_id=connection.id,
        is_active=data.is_active,
        created_by=admin.email,
        updated_by=admin.email,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Channel route already exists"
        ) from exc
    return AgentRouteOut.from_model(row)


@router.patch(
    "/profiles/{agent_id}/routes/{route_id}",
    response_model=AgentRouteOut,
    dependencies=[Depends(require_permission(AdminPermission.RUNTIME_MANAGE))],
)
async def update_route(
    agent_id: str,
    route_id: str,
    data: AgentRouteUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.RUNTIME_MANAGE)),
):
    profile = await _profile(db, agent_id)
    row = await _get(db, ChannelAgentRoute, route_id, "Channel route not found")
    if row.agent_id != profile.id:
        raise HTTPException(status_code=404, detail="Channel route not found")
    if data.channel_connection_id is not None:
        connection = await _get(
            db,
            ChannelConnection,
            data.channel_connection_id,
            "Channel connection not found",
        )
        if connection.channel != row.channel:
            raise HTTPException(
                status_code=422, detail="Route channel must match its connection"
            )
        row.channel_connection_id = connection.id
    if data.is_active is not None:
        row.is_active = data.is_active
    row.updated_by = admin.email
    return AgentRouteOut.from_model(row)


@router.post(
    "/profiles/{agent_id}/routes/{route_id}/deactivate",
    response_model=AgentRouteOut,
    dependencies=[Depends(require_permission(AdminPermission.RUNTIME_MANAGE))],
)
async def deactivate_route(
    agent_id: str,
    route_id: str,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_permission(AdminPermission.RUNTIME_MANAGE)),
):
    return await update_route(
        agent_id, route_id, AgentRouteUpdate(is_active=False), db, admin
    )
