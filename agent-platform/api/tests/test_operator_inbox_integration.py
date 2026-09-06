"""PostgreSQL coverage for the operator inbox read model."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.services.conversation_automation_assignment import (
    ConversationAutomationAssignmentService,
)
from app.services.conversation_control import (
    ConversationNotFoundError,
    conversation_control_service,
)
from app.services.operator_inbox import OperatorInboxService

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_inbox_is_agent_scoped_filterable_and_returns_a_safe_thread():
    service = OperatorInboxService()
    principal_id = None

    try:
        async with AsyncSessionLocal() as db:
            agent = (
                (
                    await db.execute(
                        select(AgentProfile).where(AgentProfile.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            admin = (
                (
                    await db.execute(
                        select(AdminUser).where(AdminUser.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            assert agent is not None, "bootstrap must provide an active agent"
            assert admin is not None, "bootstrap must provide an active admin"

            principal = Principal(display_name="Inbox integration contact")
            db.add(principal)
            await db.flush()
            conversation_status = f"test-{uuid4().hex[:20]}"
            conversation = ChatConversation(
                agent_id=agent.id,
                principal_id=principal.id,
                channel="web",
                external_thread_id=f"inbox-{uuid4()}",
                route_key="inbox-integration",
                control_mode="human",
                control_version=2,
                assigned_admin_id=admin.id,
                status=conversation_status,
                transcript_consent=True,
                consent_version="integration-v1",
            )
            db.add(conversation)
            await db.flush()
            message = ChatMessage(
                conversation_id=conversation.id,
                client_message_id=f"inbox-message-{uuid4()}",
                role="assistant",
                content="Safe operator-visible content.",
                status="completed",
                tool_names=[],
                metadata_json={
                    "origin": "operator",
                    "actor_admin_id": str(admin.id),
                    "private_provider_payload": {"must": "not leak"},
                },
            )
            db.add(message)
            await db.commit()
            principal_id = principal.id
            agent_id = agent.id
            admin_id = admin.id
            conversation_id = conversation.id

        async with AsyncSessionLocal() as db:
            page = await service.list_conversations(
                db,
                agent_id=agent_id,
                channel="web",
                control_mode="human",
                status=conversation_status,
                assigned_admin_id=admin_id,
                updated_after=datetime.now(UTC) - timedelta(minutes=5),
            )
            assert page.total == 1
            assert len(page.items) == 1
            assert page.items[0].id == conversation_id
            assert page.items[0].routing_agent.id == agent_id
            assert page.items[0].automation_agent.id == agent_id
            assert page.items[0].automation_version == 0
            assert page.items[0].assigned_operator is not None
            assert page.items[0].assigned_operator.id == admin_id

            (
                _,
                published_message,
                delivery,
            ) = await conversation_control_service.record_operator_message(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
                actor_admin_id=admin_id,
                content="Human response visible in the web inbox and event stream.",
                expected_version=2,
                idempotency_key="inbox-integration-web-publish",
            )
            assert delivery.delivery_status == "published"

            thread = await service.get_thread(
                db,
                agent_id=agent_id,
                conversation_id=conversation_id,
            )
            assert {item.content for item in thread.messages} == {
                "Safe operator-visible content.",
                "Human response visible in the web inbox and event stream.",
            }
            assert thread.messages[0].origin == "operator"
            assert not hasattr(thread.messages[0], "metadata")

            public_event = (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id == conversation_id,
                        ConversationEvent.event_type == "chat.message.completed",
                    )
                )
            ).scalar_one()
            assert public_event.visibility == "public"
            assert public_event.payload_json["message_id"] == str(published_message.id)
            assert public_event.payload_json["actor"] == "human"
            assert "actor_admin_id" not in public_event.payload_json

            with pytest.raises(ConversationNotFoundError):
                await service.get_thread(
                    db,
                    agent_id=uuid4(),
                    conversation_id=conversation_id,
                )

            operators = await service.list_operators(db, agent_id=agent_id)
            assert admin_id in {operator.id for operator in operators}
    finally:
        if principal_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Principal).where(Principal.id == principal_id))
                await db.commit()


@pytest.mark.parametrize("control_mode", ["human", "paused"])
@pytest.mark.asyncio
async def test_assignment_history_supports_human_preparation_without_route_mutation(
    control_mode: str,
):
    principal_id = None
    target_agent_id = None

    try:
        async with AsyncSessionLocal() as db:
            routing_agent = (
                (
                    await db.execute(
                        select(AgentProfile).where(AgentProfile.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            admin = (
                (
                    await db.execute(
                        select(AdminUser).where(AdminUser.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            assert routing_agent is not None
            assert admin is not None

            suffix = uuid4().hex
            target_agent = AgentProfile(
                name=f"Inbox specialist {suffix[:8]}",
                slug=f"inbox-specialist-{suffix}",
                version=1,
                is_active=True,
                is_public=False,
                retention_days=30,
                prompt_identity="Identity",
                prompt_domain="Domain",
                prompt_guardrails="Guardrails",
                unauthorized_message="Unauthorized",
                error_message="Error",
                created_by="integration-test",
            )
            principal = Principal(display_name="Assignment history contact")
            db.add_all([target_agent, principal])
            await db.flush()
            conversation = ChatConversation(
                agent_id=routing_agent.id,
                principal_id=principal.id,
                channel="web",
                external_thread_id=f"assignment-history-{uuid4()}",
                route_key=f"assignment-history-{suffix}",
                control_mode=control_mode,
                control_version=4,
                assigned_admin_id=admin.id if control_mode == "human" else None,
                status="active",
                transcript_consent=True,
                consent_version="integration-v1",
            )
            db.add(conversation)
            await db.flush()
            routing_agent_id = routing_agent.id
            target_agent_id = target_agent.id
            principal_id = principal.id
            conversation_id = conversation.id
            control_version = conversation.control_version

            result = await ConversationAutomationAssignmentService().assign(
                db,
                conversation_id=conversation.id,
                routing_agent_id=routing_agent.id,
                target_agent_id=target_agent.id,
                expected_automation_version=0,
                actor_agent_id=None,
                actor_admin_id=admin.id,
                trigger="operator_assignment",
                opportunity_id=None,
                correlation_id=f"assignment-history-{suffix}",
                idempotency_key=f"assignment-history-{suffix}",
                reason="Prepare the specialist without resuming automation.",
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            thread = await OperatorInboxService().get_thread(
                db,
                agent_id=routing_agent_id,
                conversation_id=conversation_id,
            )
            history = await OperatorInboxService().list_automation_assignments(
                db,
                agent_id=routing_agent_id,
                conversation_id=conversation_id,
                limit=10,
                offset=0,
            )
            persisted = await db.get(ChatConversation, conversation_id)

            assert result.applied is True
            assert persisted is not None
            assert persisted.agent_id == routing_agent_id
            assert persisted.automation_agent_id == target_agent_id
            assert persisted.automation_version == 1
            assert persisted.control_mode == control_mode
            assert persisted.control_version == control_version
            assert thread.conversation.routing_agent.id == routing_agent_id
            assert thread.conversation.automation_agent.id == target_agent_id
            assert thread.conversation.automation_agent.name.startswith(
                "Inbox specialist"
            )
            assert thread.conversation.automation_version == 1
            assert history.total == 1
            assert len(history.items) == 1
            assert history.items[0].event_id == result.event.id
            assert history.items[0].from_automation_agent.id == routing_agent_id
            assert history.items[0].to_automation_agent.id == target_agent_id
            assert history.items[0].automation_version == 1
            assert history.items[0].actor_admin_id == admin.id
            assert not hasattr(history.items[0], "command_hash")

            with pytest.raises(ConversationNotFoundError):
                await OperatorInboxService().list_automation_assignments(
                    db,
                    agent_id=uuid4(),
                    conversation_id=conversation_id,
                )
    finally:
        if principal_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Principal).where(Principal.id == principal_id))
                if target_agent_id is not None:
                    await db.execute(
                        delete(AgentProfile).where(AgentProfile.id == target_agent_id)
                    )
                await db.commit()
