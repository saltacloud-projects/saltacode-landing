"""PostgreSQL integration coverage for conversation ownership epochs."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.conversation_control import ConversationControlEvent
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.schemas.conversation_control import ConversationControlMode
from app.services.conversation_control import (
    ControlVersionConflictError,
    ConversationControlService,
    ConversationNotFoundError,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_control_epoch_is_scoped_and_preserves_manual_message_version():
    service = ConversationControlService()
    principal_id = None
    conversation_id = None

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

            principal = Principal(display_name="Control integration test")
            db.add(principal)
            await db.flush()
            conversation = ChatConversation(
                agent_id=agent.id,
                principal_id=principal.id,
                channel="web",
                external_thread_id=f"control-test-{uuid4()}",
                route_key="control-integration-test",
                transcript_consent=True,
                consent_version="test-v1",
            )
            db.add(conversation)
            await db.flush()
            await db.refresh(conversation)
            principal_id = principal.id
            conversation_id = conversation.id
            agent_id = agent.id
            admin_id = admin.id
            assert conversation.control_mode == "automated"
            assert conversation.control_version == 0
            assert conversation.assigned_admin_id is None
            await db.commit()

        async with AsyncSessionLocal() as db:
            controlled = await service.transition(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
                actor_admin_id=admin_id,
                target_mode=ConversationControlMode.HUMAN,
                expected_version=0,
                reason="integration takeover",
            )
            assert controlled.control_version == 1
            assert controlled.assigned_admin_id == admin_id
            await db.commit()

        async with AsyncSessionLocal() as db:
            event = (
                await db.execute(
                    select(ConversationControlEvent).where(
                        ConversationControlEvent.conversation_id == conversation_id
                    )
                )
            ).scalar_one()
            assert event.event_type == "taken_over"
            assert event.control_version == 1
            assert event.from_mode == "automated"
            assert event.to_mode == "human"

        async with AsyncSessionLocal() as db:
            with pytest.raises(ControlVersionConflictError):
                await service.transition(
                    db,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    actor_admin_id=admin_id,
                    target_mode=ConversationControlMode.PAUSED,
                    expected_version=0,
                )
            await db.rollback()

        async with AsyncSessionLocal() as db:
            unchanged = await service.get_snapshot(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
            )
            assert unchanged.control_mode == "human"
            assert unchanged.control_version == 1
            event_count = (
                await db.execute(
                    select(func.count(ConversationControlEvent.id)).where(
                        ConversationControlEvent.conversation_id == conversation_id
                    )
                )
            ).scalar_one()
            assert event_count == 1

            with pytest.raises(ConversationNotFoundError):
                await service.get_snapshot(
                    db,
                    conversation_id=conversation_id,
                    agent_id=uuid4(),
                )

        async with AsyncSessionLocal() as db:
            controlled, operator_message = await service.record_operator_message(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
                actor_admin_id=admin_id,
                content="Manual response awaiting the outbox.",
                expected_version=1,
            )
            operator_message_id = operator_message.id
            assert controlled.control_version == 1
            await db.commit()

        async with AsyncSessionLocal() as db:
            persisted_message = await db.get(ChatMessage, operator_message_id)
            persisted_control = await db.get(ChatConversation, conversation_id)
            event_count = (
                await db.execute(
                    select(func.count(ConversationControlEvent.id)).where(
                        ConversationControlEvent.conversation_id == conversation_id
                    )
                )
            ).scalar_one()
            assert persisted_message is not None
            assert persisted_message.status == "pending_delivery"
            assert persisted_message.metadata_json["control_version"] == 1
            assert persisted_control is not None
            assert persisted_control.control_version == 1
            assert event_count == 1

        async with AsyncSessionLocal() as db:
            invalid_conversation = ChatConversation(
                agent_id=agent_id,
                principal_id=principal_id,
                channel="web",
                external_thread_id=f"invalid-control-test-{uuid4()}",
                route_key="control-integration-test",
                control_mode="human",
                assigned_admin_id=None,
            )
            db.add(invalid_conversation)
            with pytest.raises(IntegrityError):
                await db.flush()
            await db.rollback()
    finally:
        if principal_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Principal).where(Principal.id == principal_id))
                await db.commit()
