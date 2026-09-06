"""Contract coverage for code-owned channel adapters and calculated readiness."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.routers.admin.agent_runtime import router
from app.schemas.agent_runtime import (
    ChannelConnectionCreate,
    ChannelConnectionUpdate,
)
from app.services.agent_runtime import ConnectionService
from app.services.channel_catalog import (
    CHANNEL_ADAPTERS,
    ChannelAdapterUnavailable,
    ChannelCatalogService,
    ChannelVersionConflict,
    require_implemented_adapter,
    resolve_channel_adapter,
)


def _connection(
    *,
    channel: str = "web",
    adapter_key: str = "web_builtin",
    active: bool = True,
    credentials: str | None = None,
    external_account_id: str | None = None,
) -> ChannelConnection:
    now = datetime.now(timezone.utc)
    return ChannelConnection(
        id=uuid4(),
        name="Connection",
        slug=f"connection-{uuid4().hex[:8]}",
        channel=channel,
        adapter_key=adapter_key,
        version=0,
        external_account_id=external_account_id,
        settings_json={},
        encrypted_credentials=credentials,
        is_active=active,
        created_at=now,
        updated_at=now,
    )


def _route(connection: ChannelConnection, *, active: bool = True):
    now = datetime.now(timezone.utc)
    return ChannelAgentRoute(
        id=uuid4(),
        agent_id=uuid4(),
        channel=connection.channel,
        version=0,
        route_key=f"route-{uuid4().hex}",
        channel_connection_id=connection.id,
        is_active=active,
        created_at=now,
        updated_at=now,
    )


def test_catalog_is_code_owned_and_exposes_planned_adapters_truthfully() -> None:
    assert [(item.channel, item.adapter_key) for item in CHANNEL_ADAPTERS] == [
        ("web", "web_builtin"),
        ("whatsapp", "meta_whatsapp_cloud"),
        ("email", "email"),
        ("instagram_dm", "meta_instagram_graph"),
        ("facebook_messenger", "meta_messenger_graph"),
    ]
    assert [item.is_implemented for item in CHANNEL_ADAPTERS] == [
        True,
        True,
        False,
        False,
        False,
    ]
    assert CHANNEL_ADAPTERS[2].blocking_codes == ("provider_required",)
    assert CHANNEL_ADAPTERS[3].blocking_codes == ("blocked_external",)

    with pytest.raises(ValidationError, match="code-owned"):
        ChannelConnectionCreate(
            name="Web",
            slug="web",
            channel="web",
            settings={"capabilities": ["outbound_media"]},
        )


def test_adapter_resolution_rejects_mismatch_and_planned_implementations() -> None:
    assert resolve_channel_adapter(channel="web").adapter_key == "web_builtin"
    with pytest.raises(ValueError, match="mismatch"):
        resolve_channel_adapter(
            channel="web",
            adapter_key="meta_whatsapp_cloud",
        )
    with pytest.raises(ChannelAdapterUnavailable, match="not_implemented"):
        require_implemented_adapter(channel="email", adapter_key="email")


@pytest.mark.asyncio
async def test_planned_adapter_is_rejected_before_persistence() -> None:
    db = SimpleNamespace(add=AsyncMock(), flush=AsyncMock())
    data = ChannelConnectionCreate(
        name="Email",
        slug="email",
        channel="email",
        adapter_key="email",
        is_active=False,
    )

    with pytest.raises(ChannelAdapterUnavailable, match="not_implemented"):
        await ConnectionService().create_channel(db, data, actor="admin@example.test")

    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_update_uses_cas_and_increments_version() -> None:
    row = _connection()
    row.version = 4
    db = SimpleNamespace(flush=AsyncMock())
    service = ConnectionService()

    with pytest.raises(ChannelVersionConflict, match="version_conflict"):
        await service.update_channel(
            db,
            row,
            ChannelConnectionUpdate(expected_version=3, name="Stale"),
            actor="admin@example.test",
        )

    await service.update_channel(
        db,
        row,
        ChannelConnectionUpdate(expected_version=4, name="Updated"),
        actor="admin@example.test",
    )

    assert row.name == "Updated"
    assert row.version == 5
    db.flush.assert_awaited_once()


def test_readiness_distinguishes_configuration_traffic_and_degradation() -> None:
    service = ChannelCatalogService()
    web = _connection()
    route = _route(web)
    unverified = service._connection_readiness(
        web,
        [route],
        last_inbound_at=None,
        last_outbound_at=None,
    )
    assert unverified.readiness == "configured_unverified"
    assert unverified.credentials_state == "not_required"
    assert unverified.routing_state == "active"
    assert unverified.blocking_codes == ("traffic_not_observed",)

    observed_at = datetime.now(timezone.utc)
    observed = service._connection_readiness(
        web,
        [route],
        last_inbound_at=observed_at,
        last_outbound_at=None,
    )
    assert observed.readiness == "traffic_observed"
    assert observed.last_inbound_at == observed_at
    assert observed.last_outbound_at is None

    whatsapp = _connection(
        channel="whatsapp",
        adapter_key="meta_whatsapp_cloud",
        external_account_id="123456",
    )
    degraded = service._connection_readiness(
        whatsapp,
        [_route(whatsapp)],
        last_inbound_at=observed_at,
        last_outbound_at=None,
    )
    assert degraded.readiness == "degraded"
    assert degraded.credentials_state == "missing"
    assert "credentials_missing" in degraded.blocking_codes


def test_admin_catalog_is_authenticated_and_does_not_expose_route_ownership() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")
    operation = app.openapi()["paths"]["/api/admin/channel-catalog"]["get"]
    connection_schema = app.openapi()["components"]["schemas"][
        "ChannelConnectionReadinessOut"
    ]["properties"]

    assert operation["security"] == [{"HTTPBearer": []}]
    assert "agent_id" not in connection_schema
    assert "route_key" not in connection_schema
    assert "adapter_implemented" in connection_schema
    assert "settings_valid" in connection_schema
    assert "credentials_state" in connection_schema
    assert "routing_state" in connection_schema
    assert "last_inbound_at" in connection_schema
    assert "last_outbound_at" in connection_schema
