"""PostgreSQL coverage for private web commercial-contact capture."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import delete, select

from app.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_handoff_route import AgentHandoffRoute
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.conversation_event import ConversationEvent
from app.models.opportunity import (
    FollowUpTask,
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.routers.web_chat_v2 import router as web_chat_router
from app.routers.web_commercial import router

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class WebCommercialGraph:
    source_agent_id: UUID
    target_agent_id: UUID
    admin_id: UUID
    admin_role_key: str
    connection_id: UUID
    channel_route_id: UUID
    handoff_route_id: UUID
    principal_id: UUID
    other_principal_id: UUID
    identity_id: UUID
    conversation_id: UUID
    session_id: UUID
    route_key: str


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
def contact_crypto_keys(monkeypatch, tmp_path) -> None:
    encryption_key = tmp_path / "contact-data.key"
    lookup_key = tmp_path / "contact-lookup.key"
    encryption_key.write_bytes(Fernet.generate_key())
    lookup_key.write_bytes(b"web-commercial-lookup-key-32-bytes-minimum")
    monkeypatch.setattr(settings, "contact_encryption_key_file", encryption_key)
    monkeypatch.setattr(settings, "contact_lookup_hmac_key_file", lookup_key)


def _agent(label: str, *, public: bool) -> AgentProfile:
    return AgentProfile(
        name=f"Web commercial {label}",
        slug=f"web-commercial-{label}-{uuid4().hex}",
        version=1,
        is_active=True,
        is_public=public,
        retention_days=30,
        description=None,
        prompt_identity="Test identity",
        prompt_domain="Test domain",
        prompt_guardrails="Test guardrails",
        unauthorized_message="Unauthorized",
        error_message="Error",
        created_by="integration-test",
    )


@pytest.fixture
async def web_commercial_graph() -> WebCommercialGraph:
    suffix = uuid4().hex
    session_id = uuid4()
    route_key = f"web-commercial-{suffix}"
    async with AsyncSessionLocal() as db:
        source = _agent("source", public=True)
        target = _agent("target", public=False)
        role = AdminRole(
            key=f"web-commercial-{suffix}"[:40],
            name="Web commercial test role",
            description=None,
            permissions=[],
            is_active=True,
            is_system=False,
        )
        admin = AdminUser(
            email=f"web-commercial-{suffix}@example.test",
            hashed_password="not-used",
            name="Web commercial test admin",
            role=role.key,
            is_active=True,
            must_change_password=False,
        )
        connection = ChannelConnection(
            name="Web commercial",
            slug=f"web-commercial-{suffix}",
            channel="web",
            settings_json={},
            is_active=True,
        )
        principal = Principal(display_name="Commercial lead")
        other_principal = Principal(display_name="Mismatched lead")
        db.add_all(
            [source, target, role, admin, connection, principal, other_principal]
        )
        await db.flush()
        channel_route = ChannelAgentRoute(
            channel="web",
            route_key=route_key,
            channel_connection_id=connection.id,
            agent_id=source.id,
            is_active=True,
        )
        identity = ChannelIdentity(
            principal_id=principal.id,
            channel="web",
            route_key=route_key,
            external_subject=str(session_id),
            verified=False,
        )
        db.add_all([channel_route, identity])
        await db.flush()
        conversation = ChatConversation(
            agent_id=source.id,
            principal_id=principal.id,
            channel="web",
            route_key=route_key,
            external_thread_id=str(session_id),
            channel_route_id=channel_route.id,
            status="active",
            control_mode="automated",
        )
        handoff_route = AgentHandoffRoute(
            source_agent_id=source.id,
            target_agent_id=target.id,
            trigger="quote_requested",
            is_active=True,
            control_version=0,
            created_by_admin_id=admin.id,
            updated_by_admin_id=admin.id,
        )
        db.add_all([conversation, handoff_route])
        await db.commit()
        graph = WebCommercialGraph(
            source_agent_id=source.id,
            target_agent_id=target.id,
            admin_id=admin.id,
            admin_role_key=role.key,
            connection_id=connection.id,
            channel_route_id=channel_route.id,
            handoff_route_id=handoff_route.id,
            principal_id=principal.id,
            other_principal_id=other_principal.id,
            identity_id=identity.id,
            conversation_id=conversation.id,
            session_id=session_id,
            route_key=route_key,
        )

    try:
        yield graph
    finally:
        async with AsyncSessionLocal() as db:
            opportunity_ids = select(Opportunity.id).where(
                Opportunity.created_by_agent_id == graph.source_agent_id
            )
            await db.execute(
                delete(FollowUpTask).where(
                    FollowUpTask.opportunity_id.in_(opportunity_ids)
                )
            )
            await db.execute(
                delete(OpportunityConversation).where(
                    OpportunityConversation.opportunity_id.in_(opportunity_ids)
                )
            )
            await db.execute(
                delete(OpportunityOwnershipEvent).where(
                    OpportunityOwnershipEvent.opportunity_id.in_(opportunity_ids)
                )
            )
            await db.execute(
                delete(OpportunityStageEvent).where(
                    OpportunityStageEvent.opportunity_id.in_(opportunity_ids)
                )
            )
            await db.execute(
                delete(Opportunity).where(
                    Opportunity.created_by_agent_id == graph.source_agent_id
                )
            )
            await db.execute(
                delete(ConsentRecord).where(
                    ConsentRecord.agent_id == graph.source_agent_id
                )
            )
            await db.execute(
                delete(Contact).where(Contact.principal_id == graph.principal_id)
            )
            await db.execute(
                delete(ChatConversation).where(
                    ChatConversation.id == graph.conversation_id
                )
            )
            await db.execute(
                delete(ChannelIdentity).where(ChannelIdentity.id == graph.identity_id)
            )
            await db.execute(
                delete(AgentHandoffRoute).where(
                    AgentHandoffRoute.id == graph.handoff_route_id
                )
            )
            await db.execute(
                delete(ChannelAgentRoute).where(
                    ChannelAgentRoute.id == graph.channel_route_id
                )
            )
            await db.execute(
                delete(ChannelConnection).where(
                    ChannelConnection.id == graph.connection_id
                )
            )
            await db.execute(
                delete(Principal).where(
                    Principal.id.in_([graph.principal_id, graph.other_principal_id])
                )
            )
            await db.execute(delete(AdminUser).where(AdminUser.id == graph.admin_id))
            await db.execute(
                delete(AdminRole).where(AdminRole.key == graph.admin_role_key)
            )
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_([graph.source_agent_id, graph.target_agent_id])
                )
            )
            await db.commit()


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(web_chat_router)
    app.include_router(router)
    return app


def _payload(graph: WebCommercialGraph, *, request_id: UUID) -> dict:
    return {
        "session_id": str(graph.session_id),
        "route_key": graph.route_key,
        "client_request_id": str(request_id),
        "locale": "es-AR",
        "policy_version": "commercial-privacy-v1",
        "title": "Custom software quote",
        "summary": "A structured lead request",
        "contact_kind": "email",
        "contact_value": "lead@example.com",
        "preferred_delivery_channel": "email",
        "quote_delivery_consent": True,
        "commercial_follow_up_consent": True,
    }


@pytest.mark.asyncio
async def test_capture_is_atomic_idempotent_encrypted_and_publicly_safe(
    contact_crypto_keys,
    web_commercial_graph: WebCommercialGraph,
) -> None:
    graph = web_commercial_graph
    payload = _payload(graph, request_id=uuid4())
    headers = {"Authorization": f"Bearer {settings.fastapi_api_key}"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        headers=headers,
    ) as client:
        first = await client.post(
            "/internal/v2/web/commercial-contact",
            json=payload,
        )
        duplicate = await client.post(
            "/internal/v2/web/commercial-contact",
            json=payload,
        )
        conflicting_payload = {
            **payload,
            "policy_version": "commercial-privacy-v2",
            "contact_value": "another-lead@example.com",
            "commercial_follow_up_consent": False,
        }
        conflict = await client.post(
            "/internal/v2/web/commercial-contact",
            json=conflicting_payload,
        )
        public_events = await client.get(
            "/internal/v2/web/events",
            params={
                "session_id": str(graph.session_id),
                "route_key": graph.route_key,
                "after": 0,
            },
        )

    assert first.status_code == 202, first.text
    assert duplicate.status_code == 202
    assert duplicate.json() == first.json()
    assert conflict.status_code == 409
    assert public_events.status_code == 200
    assert first.json()["target_agent_id"] == str(graph.target_agent_id)
    assert first.json()["status"] == "accepted"
    assert public_events.json()["events"] == [
        {
            "schema_version": "2",
            "cursor": 2,
            "event_type": "commercial.opportunity.created",
            "occurred_at": public_events.json()["events"][0]["occurred_at"],
            "payload": {
                "client_request_id": payload["client_request_id"],
                "opportunity_id": first.json()["opportunity_id"],
                "preferred_delivery_channel": "email",
                "status": "accepted",
            },
        }
    ]

    async with AsyncSessionLocal() as db:
        contacts = list((await db.execute(select(Contact))).scalars().all())
        points = list((await db.execute(select(ContactPoint))).scalars().all())
        consents = list(
            (
                await db.execute(
                    select(ConsentRecord).where(
                        ConsentRecord.agent_id == graph.source_agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
        opportunities = list(
            (
                await db.execute(
                    select(Opportunity).where(
                        Opportunity.created_by_agent_id == graph.source_agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
        events = list(
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == graph.conversation_id,
                        ConversationEvent.event_type
                        == "commercial.opportunity.created",
                    )
                )
            )
            .scalars()
            .all()
        )
        receipts = list(
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == graph.conversation_id,
                        ConversationEvent.event_type == "commercial.contact.requested",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(contacts) == 1
    assert len(points) == 1
    assert "lead@example.com" not in points[0].ciphertext
    assert {record.purpose for record in consents} == {
        "quote_delivery",
        "commercial_follow_up",
    }
    assert len(opportunities) == 1
    assert len(events) == 1
    assert len(receipts) == 1
    assert events[0].visibility == "public"
    assert events[0].payload_json == {
        "client_request_id": payload["client_request_id"],
        "opportunity_id": first.json()["opportunity_id"],
        "preferred_delivery_channel": "email",
        "status": "accepted",
    }
    serialized_event = str(events[0].payload_json)
    assert payload["contact_value"] not in serialized_event
    assert payload["title"] not in serialized_event
    assert payload["summary"] not in serialized_event
    assert receipts[0].visibility == "internal"
    assert receipts[0].payload_json["client_request_id"] == payload["client_request_id"]
    assert len(receipts[0].payload_json["command_fingerprint"]) == 64
    serialized_receipt = str(receipts[0].payload_json)
    assert payload["contact_value"] not in serialized_receipt
    assert conflicting_payload["contact_value"] not in serialized_receipt
    assert payload["title"] not in serialized_receipt
    assert payload["summary"] not in serialized_receipt


@pytest.mark.asyncio
async def test_closed_or_mismatched_sessions_fail_closed(
    contact_crypto_keys,
    web_commercial_graph: WebCommercialGraph,
) -> None:
    graph = web_commercial_graph
    headers = {"Authorization": f"Bearer {settings.fastapi_api_key}"}

    async with AsyncSessionLocal() as db:
        conversation = await db.get(ChatConversation, graph.conversation_id)
        conversation.status = "closed"
        conversation.control_mode = "closed"
        await db.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        headers=headers,
    ) as client:
        closed = await client.post(
            "/internal/v2/web/commercial-contact",
            json=_payload(graph, request_id=uuid4()),
        )
    assert closed.status_code == 423

    async with AsyncSessionLocal() as db:
        conversation = await db.get(ChatConversation, graph.conversation_id)
        conversation.status = "active"
        conversation.control_mode = "automated"
        identity = await db.get(ChannelIdentity, graph.identity_id)
        identity.principal_id = graph.other_principal_id
        await db.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        headers=headers,
    ) as client:
        mismatch = await client.post(
            "/internal/v2/web/commercial-contact",
            json=_payload(graph, request_id=uuid4()),
        )
    assert mismatch.status_code == 423


@pytest.mark.asyncio
async def test_missing_handoff_route_rolls_back_contact_and_consent(
    contact_crypto_keys,
    web_commercial_graph: WebCommercialGraph,
) -> None:
    graph = web_commercial_graph
    headers = {"Authorization": f"Bearer {settings.fastapi_api_key}"}
    async with AsyncSessionLocal() as db:
        route = await db.get(AgentHandoffRoute, graph.handoff_route_id)
        route.is_active = False
        await db.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        headers=headers,
    ) as client:
        response = await client.post(
            "/internal/v2/web/commercial-contact",
            json=_payload(graph, request_id=uuid4()),
        )
    assert response.status_code == 503, response.text

    async with AsyncSessionLocal() as db:
        contact_count = len(
            (
                await db.execute(
                    select(Contact).where(Contact.principal_id == graph.principal_id)
                )
            )
            .scalars()
            .all()
        )
        consent_count = len(
            (
                await db.execute(
                    select(ConsentRecord).where(
                        ConsentRecord.agent_id == graph.source_agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert contact_count == 0
    assert consent_count == 0
