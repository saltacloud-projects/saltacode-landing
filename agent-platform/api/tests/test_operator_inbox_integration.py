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
