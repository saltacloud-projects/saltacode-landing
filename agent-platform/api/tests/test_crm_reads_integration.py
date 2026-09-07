"""PostgreSQL proofs for authorized CRM pagination and changing ownership."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionLocal
from app.dependencies import get_db
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.audit_log import AuditLog
from app.models.channel_inbound import ChannelInboundJob
from app.models.contact import ConsentRecord, Contact
from app.models.follow_up import FollowUpTask
from app.models.meeting import Meeting
from app.models.opportunity import Opportunity
from app.models.outbound import OutboundMessage
from app.models.platform import ChatConversation, Principal
from app.routers.admin.auth import require_admin
from app.routers.admin.crm import router
from app.services.commercial.follow_up_read_models import (
    FollowUpReadNotFoundError,
    follow_up_read_service,
)
from app.services.commercial.meeting_read_models import (
    MeetingReadNotFoundError,
    meeting_read_service,
)

pytestmark = pytest.mark.integration

RESOURCE_PERMISSIONS = {
    "inbox": "conversations.read",
    "opportunities": "opportunities.read",
    "meetings": "meetings.read",
    "follow-ups": "follow_ups.read",
    "deliveries": "deliveries.read",
    "inbound-jobs": "inbound.read",
    "audit": "audit.read",
}


@dataclass
class CrmRows:
    agent: AgentProfile
    items: dict
    opportunity: Opportunity
    task: FollowUpTask
    meeting: Meeting
    conversation: ChatConversation


async def _create_rows(db, name: str) -> CrmRows:
    suffix = uuid4().hex
    now = datetime.now(UTC)
    agent = AgentProfile(
        name=name,
        slug=f"crm-{suffix}",
        is_active=True,
        prompt_identity="Test identity",
        prompt_domain="Test domain",
        prompt_guardrails="Test boundaries",
        unauthorized_message="Unavailable",
        error_message="Try again",
    )
    principal = Principal(display_name=f"CRM contact {name}")
    connection = ChannelConnection(
        name=f"CRM {name}",
        slug=f"crm-{suffix}",
        channel="whatsapp",
        adapter_key="meta_whatsapp_cloud",
        is_active=False,
    )
    db.add_all([agent, principal, connection])
    await db.flush()
    route = ChannelAgentRoute(
        channel="whatsapp",
        route_key=f"crm-{suffix}",
        channel_connection_id=connection.id,
        agent_id=agent.id,
        is_active=False,
    )
    conversation = ChatConversation(
        agent_id=agent.id,
        automation_agent_id=agent.id,
        principal_id=principal.id,
        channel="web",
        route_key=f"crm-{suffix}",
        external_thread_id=suffix,
        transcript_consent=True,
        consent_version="crm-test-v1",
    )
    contact = Contact(principal_id=principal.id, created_by_agent_id=agent.id)
    db.add_all([route, conversation, contact])
    await db.flush()
    command = {
        "command_hash": "a" * 64,
        "correlation_id": suffix,
        "idempotency_key": suffix,
    }
    opportunity = Opportunity(
        contact_id=contact.id,
        created_by_agent_id=agent.id,
        assigned_agent_id=agent.id,
        title=f"CRM {name}",
        **command,
    )
    consent = ConsentRecord(
        agent_id=agent.id,
        principal_id=principal.id,
        contact_id=contact.id,
        purpose="commercial_follow_up",
        action="grant",
        channel="web",
        locale="es",
        policy_version="crm-test-v1",
        **command,
    )
    db.add_all([opportunity, consent])
    await db.flush()
    task = FollowUpTask(
        opportunity_id=opportunity.id,
        consent_record_id=consent.id,
        assigned_agent_id=agent.id,
        kind="commercial_follow_up",
        status="review_required",
        review_required_at=now,
        last_safe_code="test_review",
        due_at=now,
        available_at=now,
        **command,
    )
    meeting = Meeting(
        opportunity_id=opportunity.id,
        created_under_agent_id=agent.id,
        created_by_agent_id=agent.id,
        **command,
    )
    delivery = OutboundMessage(
        conversation_id=conversation.id,
        agent_id=agent.id,
        channel_route_id=route.id,
        kind="text",
        payload_json={"text": "Private fixture body"},
        destination="synthetic-destination",
        sender_type="system",
        control_version=0,
        sequence=1,
        idempotency_key=suffix,
        payload_hash="b" * 64,
        correlation_id=suffix,
        status="failed",
    )
    inbound = ChannelInboundJob(
        channel="whatsapp",
        adapter_key="meta_whatsapp_cloud",
        adapter_version=1,
        channel_route_id=route.id,
        channel_route_version=0,
        route_key_snapshot=route.route_key,
        channel_connection_id=connection.id,
        channel_connection_version=0,
        routing_agent_id=agent.id,
        provider_message_id=suffix,
        status="completed",
        phase="terminal",
        terminal_at=now,
        conversation_id=conversation.id,
    )
    audit = AuditLog(
        agent_id=agent.id, phone_number="synthetic", channel="web", status="success"
    )
    db.add_all([task, meeting, delivery, inbound, audit])
    await db.flush()
    return CrmRows(
        agent,
        {
            "inbox": conversation.id,
            "opportunities": opportunity.id,
            "meetings": meeting.id,
            "follow-ups": task.id,
            "deliveries": delivery.id,
            "inbound-jobs": inbound.id,
            "audit": audit.id,
        },
        opportunity,
        task,
        meeting,
        conversation,
    )


@pytest.fixture
async def crm_context():
    # All fixtures remain in one uncommitted transaction and are rolled back.
    async with AsyncSessionLocal() as db:
        try:
            first = await _create_rows(db, "A intake")
            second = await _create_rows(db, "B restricted")
            third = await _create_rows(db, "C specialist")
            role = AdminRole(
                key=f"crm-{uuid4().hex[:20]}",
                name="CRM operator",
                permissions=[*RESOURCE_PERMISSIONS.values(), "conversations.manage"],
            )
            db.add(role)
            await db.flush()
            admin = AdminUser(
                name="CRM fixture",
                email=f"crm-{uuid4().hex}@example.invalid",
                hashed_password="not-a-login",
                role=role.key,
            )
            db.add(admin)
            await db.flush()
            first_grant = AdminAgentGrant(
                admin_user_id=admin.id,
                agent_id=first.agent.id,
                permissions=["*"],
                is_active=True,
            )
            second_grant = AdminAgentGrant(
                admin_user_id=admin.id,
                agent_id=second.agent.id,
                permissions=["*"],
                is_active=False,
            )
            third_grant = AdminAgentGrant(
                admin_user_id=admin.id,
                agent_id=third.agent.id,
                permissions=list(RESOURCE_PERMISSIONS.values()),
                is_active=True,
            )
            legacy_audit = AuditLog(
                agent_id=None, phone_number="synthetic", channel="web", status="success"
            )
            db.add_all([first_grant, second_grant, third_grant, legacy_audit])
            await db.flush()
            app = FastAPI()
            app.include_router(router, prefix="/api/admin/crm")
            app.dependency_overrides[require_admin] = lambda: admin
            app.dependency_overrides[get_db] = lambda: db
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                yield client, db, first, second, third, role, third_grant
        finally:
            await db.rollback()


@pytest.mark.parametrize("resource", RESOURCE_PERMISSIONS)
async def test_each_collection_applies_grants_before_count_and_pagination(
    crm_context, resource
):
    client, _db, first, second, third, _role, _grant = crm_context
    pages = []
    for offset in (0, 1):
        response = await client.get(
            f"/api/admin/crm/{resource}", params={"limit": 1, "offset": offset}
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 2
        assert page["limit"] == 1 and page["offset"] == offset
        assert len(page["items"]) == 1
        pages.extend(page["items"])
    assert {item["id"] for item in pages} == {
        str(first.items[resource]),
        str(third.items[resource]),
    }
    assert {item["owner_agent_id"] for item in pages} == {
        str(first.agent.id),
        str(third.agent.id),
    }
    assert all("profiles.read" not in item["capabilities"] for item in pages)
    first_item = next(
        item for item in pages if item["owner_agent_id"] == str(first.agent.id)
    )
    third_item = next(
        item for item in pages if item["owner_agent_id"] == str(third.agent.id)
    )
    assert "conversations.manage" in first_item["capabilities"]
    assert "conversations.manage" not in third_item["capabilities"]
    catalog = await client.get(f"/api/admin/crm/{resource}/agents")
    assert catalog.status_code == 200
    assert {item["id"] for item in catalog.json()} == {
        str(first.agent.id),
        str(third.agent.id),
    }
    assert all(item["is_active"] for item in catalog.json())
    assert (
        await client.get(
            f"/api/admin/crm/{resource}", params={"agent_id": str(second.agent.id)}
        )
    ).status_code == 403
    filtered = await client.get(
        f"/api/admin/crm/{resource}", params={"agent_id": str(first.agent.id)}
    )
    assert filtered.json()["total"] == 1
    beyond = await client.get(f"/api/admin/crm/{resource}", params={"offset": 2})
    assert beyond.json()["items"] == [] and beyond.json()["total"] == 2
    if resource in {"inbox", "meetings", "follow-ups", "deliveries", "inbound-jobs"}:
        assert "Private fixture body" not in str(pages)


async def test_operation_specific_grants_and_role_revocation_are_not_profile_access(
    crm_context,
):
    client, db, first, _second, third, role, third_grant = crm_context
    third_grant.permissions = ["conversations.read"]
    await db.flush()
    assert (await client.get("/api/admin/crm/inbox")).json()["total"] == 2
    opportunities = (await client.get("/api/admin/crm/opportunities")).json()
    assert opportunities["total"] == 1
    assert opportunities["items"][0]["owner_agent_id"] == str(first.agent.id)
    assert (
        await client.get(
            "/api/admin/crm/opportunities", params={"agent_id": str(third.agent.id)}
        )
    ).status_code == 403
    role.permissions = ["profiles.read"]
    await db.flush()
    assert (await client.get("/api/admin/crm/inbox")).status_code == 403
    assert (await client.get("/api/admin/crm/inbox/agents")).status_code == 403


async def test_followups_and_meetings_use_current_opportunity_owner_not_snapshot(
    crm_context,
):
    client, db, first, second, third, _role, _grant = crm_context
    first.opportunity.assigned_agent_id = third.agent.id
    first.conversation.automation_agent_id = third.agent.id
    await db.flush()
    for resource, item_id in (
        ("follow-ups", first.task.id),
        ("meetings", first.meeting.id),
    ):
        page = (await client.get(f"/api/admin/crm/{resource}")).json()
        item = next(item for item in page["items"] if item["id"] == str(item_id))
        assert item["owner_agent_id"] == str(third.agent.id)
        if resource == "follow-ups":
            assert item["assigned_agent_id"] == str(first.agent.id)
    inbox = (await client.get("/api/admin/crm/inbox")).json()
    thread = next(
        item for item in inbox["items"] if item["id"] == str(first.conversation.id)
    )
    assert thread["owner_agent_id"] == str(first.agent.id)
    assert thread["automation_agent"]["id"] == str(third.agent.id)
    with pytest.raises(FollowUpReadNotFoundError):
        await follow_up_read_service.get_task(
            db, agent_id=first.agent.id, task_id=first.task.id
        )
    with pytest.raises(MeetingReadNotFoundError):
        await meeting_read_service.get_meeting(
            db, agent_id=first.agent.id, meeting_id=first.meeting.id
        )
    first.opportunity.assigned_agent_id = second.agent.id
    await db.flush()
    for resource in ("opportunities", "follow-ups", "meetings"):
        assert (await client.get(f"/api/admin/crm/{resource}")).json()["total"] == 1


@pytest.mark.parametrize("resource", RESOURCE_PERMISSIONS)
async def test_empty_authorized_scope_never_becomes_unrestricted(crm_context, resource):
    client, db, _first, _second, _third, _role, _grant = crm_context
    from sqlalchemy import update

    await db.execute(
        update(AdminAgentGrant)
        .where(
            AdminAgentGrant.agent_id.in_(
                (_first.agent.id, _second.agent.id, _third.agent.id)
            )
        )
        .values(is_active=False)
    )
    page = (await client.get(f"/api/admin/crm/{resource}")).json()
    assert page["items"] == [] and page["total"] == 0
    assert (await client.get(f"/api/admin/crm/{resource}/agents")).json() == []


async def test_contact_identity_does_not_authorize_foreign_conversation_candidates_or_links(
    crm_context,
):
    from app.services.commercial.opportunities import (
        InvalidOpportunityCommandError,
        opportunity_service,
    )
    from app.services.commercial.read_models import commercial_read_service

    _client, db, first, second, _third, _role, _grant = crm_context
    foreign_conversation = ChatConversation(
        agent_id=second.agent.id,
        automation_agent_id=second.agent.id,
        principal_id=first.conversation.principal_id,
        channel="web",
        route_key=f"crm-foreign-{uuid4().hex}",
        external_thread_id=uuid4().hex,
        transcript_consent=True,
        consent_version="crm-test-v1",
    )
    db.add(foreign_conversation)
    await db.flush()
    detail = await commercial_read_service.get_opportunity(
        db, agent_id=first.agent.id, opportunity_id=first.opportunity.id
    )
    assert [item.id for item in detail.available_conversations] == [
        first.conversation.id
    ]
    with pytest.raises(InvalidOpportunityCommandError):
        await opportunity_service.link_conversation(
            db,
            opportunity_id=first.opportunity.id,
            conversation_id=foreign_conversation.id,
            actor_agent_id=first.agent.id,
            actor_operator_id=None,
            correlation_id=uuid4().hex,
            idempotency_key=uuid4().hex,
        )
    key = uuid4().hex
    linked = await opportunity_service.link_conversation(
        db,
        opportunity_id=first.opportunity.id,
        conversation_id=first.conversation.id,
        actor_agent_id=first.agent.id,
        actor_operator_id=None,
        correlation_id=uuid4().hex,
        idempotency_key=key,
    )
    assert linked.created
    replay = await opportunity_service.link_conversation(
        db,
        opportunity_id=first.opportunity.id,
        conversation_id=first.conversation.id,
        actor_agent_id=first.agent.id,
        actor_operator_id=None,
        correlation_id=uuid4().hex,
        idempotency_key=key,
    )
    assert not replay.created
