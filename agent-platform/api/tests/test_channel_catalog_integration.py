"""PostgreSQL coverage for channel CAS, readiness evidence, and route isolation."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.models.whatsapp_inbox import WhatsAppInboundJob
from app.routers.admin.agent_runtime import (
    create_channel,
    list_routes,
    update_route,
)
from app.schemas.agent_runtime import (
    AgentRouteUpdate,
    ChannelConnectionCreate,
)
from app.services.channel_catalog import channel_catalog_service

pytestmark = pytest.mark.integration


def _profile(label: str) -> AgentProfile:
    return AgentProfile(
        name=f"Channel catalog {label}",
        slug=f"channel-catalog-{label}-{uuid4().hex[:8]}",
        version=1,
        is_active=True,
        is_public=False,
        retention_days=30,
        prompt_identity="identity",
        prompt_domain="domain",
        prompt_guardrails="guardrails",
        unauthorized_message="unauthorized",
        error_message="error",
    )


@pytest.mark.asyncio
async def test_postgres_rejects_planned_creation_and_preserves_route_isolation() -> (
    None
):
    async with AsyncSessionLocal() as db:
        transaction = await db.begin()
        try:
            agent_a = _profile("a")
            agent_b = _profile("b")
            db.add_all([agent_a, agent_b])
            await db.flush()
            admin = SimpleNamespace(email="channel-catalog@example.test")

            with pytest.raises(HTTPException) as unavailable:
                await create_channel(
                    ChannelConnectionCreate(
                        name="Planned email",
                        slug=f"planned-email-{uuid4().hex[:8]}",
                        channel="email",
                        adapter_key="email",
                        is_active=False,
                    ),
                    db,
                    admin,
                )
            assert unavailable.value.status_code == 422
            assert unavailable.value.detail == "channel_adapter_not_implemented"

            web = ChannelConnection(
                name="Integration web",
                slug=f"integration-web-{uuid4().hex[:8]}",
                channel="web",
                adapter_key="web_builtin",
                version=0,
                external_account_id=None,
                settings_json={},
                is_active=True,
            )
            whatsapp = ChannelConnection(
                name="Integration WhatsApp",
                slug=f"integration-whatsapp-{uuid4().hex[:8]}",
                channel="whatsapp",
                adapter_key="meta_whatsapp_cloud",
                version=0,
                external_account_id=f"1{uuid4().int % 10**14:014d}",
                settings_json={},
                encrypted_credentials=None,
                is_active=True,
            )
            db.add_all([web, whatsapp])
            await db.flush()

            route_a = ChannelAgentRoute(
                agent_id=agent_a.id,
                channel="web",
                version=0,
                route_key=f"catalog-web-a-{uuid4().hex}",
                channel_connection_id=web.id,
                is_active=True,
            )
            route_b = ChannelAgentRoute(
                agent_id=agent_b.id,
                channel="web",
                version=0,
                route_key=f"catalog-web-b-{uuid4().hex}",
                channel_connection_id=web.id,
                is_active=True,
            )
            whatsapp_route = ChannelAgentRoute(
                agent_id=agent_a.id,
                channel="whatsapp",
                version=0,
                route_key=f"catalog-whatsapp-{uuid4().hex}",
                channel_connection_id=whatsapp.id,
                is_active=True,
            )
            db.add_all([route_a, route_b, whatsapp_route])
            await db.flush()

            changed = await update_route(
                str(agent_a.id),
                str(route_a.id),
                AgentRouteUpdate(expected_version=0, is_active=False),
                db,
                admin,
            )
            assert changed.version == 1
            with pytest.raises(HTTPException) as conflict:
                await update_route(
                    str(agent_a.id),
                    str(route_a.id),
                    AgentRouteUpdate(expected_version=0, is_active=True),
                    db,
                    admin,
                )
            assert conflict.value.status_code == 409
            assert conflict.value.detail == "channel_route_version_conflict"

            agent_a_routes = await list_routes(str(agent_a.id), db)
            assert {row.id for row in agent_a_routes} == {
                str(route_a.id),
                str(whatsapp_route.id),
            }
            assert str(route_b.id) not in {row.id for row in agent_a_routes}

            principal = Principal(display_name="Catalog evidence")
            db.add(principal)
            await db.flush()
            conversation = ChatConversation(
                agent_id=agent_b.id,
                automation_agent_id=agent_b.id,
                automation_version=0,
                principal_id=principal.id,
                channel="web",
                external_thread_id=f"catalog-thread-{uuid4().hex}",
                route_key=route_b.route_key,
                channel_route_id=route_b.id,
                status="active",
                control_mode="automated",
                control_version=0,
                next_outbound_sequence=1,
                next_event_sequence=1,
            )
            db.add(conversation)
            await db.flush()
            db.add(
                ChatMessage(
                    conversation_id=conversation.id,
                    client_message_id=f"catalog-message-{uuid4().hex}",
                    role="user",
                    content="Hello",
                    status="completed",
                )
            )
            db.add(
                WhatsAppInboundJob(
                    channel_route_id=whatsapp_route.id,
                    channel_connection_id=whatsapp.id,
                    provider_message_id=f"catalog-provider-{uuid4().hex}",
                    payload_json={},
                    status="queued",
                    attempts=0,
                    max_attempts=5,
                )
            )
            await db.flush()

            readiness = {
                item.connection.id: item
                for item in await channel_catalog_service.list_readiness(db)
            }
            assert readiness[web.id].readiness == "traffic_observed"
            assert readiness[web.id].last_inbound_at is not None
            assert readiness[web.id].last_outbound_at is None
            assert readiness[whatsapp.id].readiness == "degraded"
            assert readiness[whatsapp.id].credentials_state == "missing"

            planned = (
                await db.execute(
                    select(ChannelConnection).where(
                        ChannelConnection.adapter_key == "email"
                    )
                )
            ).scalar_one_or_none()
            assert planned is None
        finally:
            await transaction.rollback()
