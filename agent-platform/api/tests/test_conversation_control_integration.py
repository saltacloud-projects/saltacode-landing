"""PostgreSQL integration coverage for conversation ownership epochs."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.conversation_control import ConversationControlEvent
from app.models.outbound import OutboundMessage
from app.models.platform import ChatConversation, ChatMessage, Principal
from app.schemas.conversation_control import ConversationControlMode
from app.services.chat_application import ChatApplicationService
from app.services.conversation_control import (
    ControlVersionConflictError,
    ConversationControlService,
    ConversationNotFoundError,
    OperatorMessagePersistenceError,
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
    route_id = None
    connection_id = None

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

            connection = ChannelConnection(
                name="Control integration connection",
                slug=f"control-connection-{uuid4().hex}",
                channel="whatsapp",
                external_account_id=f"control-account-{uuid4().hex}",
                settings_json={},
                is_active=True,
            )
            db.add(connection)
            await db.flush()
            route = ChannelAgentRoute(
                channel="whatsapp",
                route_key=f"control-route-{uuid4().hex}",
                channel_connection_id=connection.id,
                agent_id=agent.id,
                is_active=True,
            )
            db.add(route)
            await db.flush()

            principal = Principal(display_name="Control integration test")
            db.add(principal)
            await db.flush()
            conversation = ChatConversation(
                agent_id=agent.id,
                principal_id=principal.id,
                channel="whatsapp",
                external_thread_id="5493870000000",
                route_key=route.route_key,
                channel_route_id=route.id,
                transcript_consent=True,
                consent_version="test-v1",
            )
            db.add(conversation)
            await db.flush()
            await db.refresh(conversation)
            principal_id = principal.id
            conversation_id = conversation.id
            route_id = route.id
            connection_id = connection.id
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
            controlled = await service.get_snapshot(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
            )
            inbound_service = ChatApplicationService()
            inbound = await inbound_service.record_whatsapp_inbound(
                db,
                conversation=controlled,
                request_id="wamid.manual-visible",
                content="This message must remain visible during takeover.",
            )
            duplicate = await inbound_service.record_whatsapp_inbound(
                db,
                conversation=controlled,
                request_id="wamid.manual-visible",
                content="This message must remain visible during takeover.",
            )
            inbound_id = inbound.id
            assert duplicate.id == inbound.id
            await db.commit()

        async with AsyncSessionLocal() as db:
            persisted_inbound = await db.get(ChatMessage, inbound_id)
            automatic_outbound_count = (
                await db.execute(
                    select(func.count(OutboundMessage.id)).where(
                        OutboundMessage.chat_message_id == inbound_id
                    )
                )
            ).scalar_one()
            assert persisted_inbound is not None
            assert persisted_inbound.role == "user"
            assert persisted_inbound.content == (
                "This message must remain visible during takeover."
            )
            assert automatic_outbound_count == 0

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
            (
                controlled,
                operator_message,
                operator_outbound,
            ) = await service.record_operator_message(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
                actor_admin_id=admin_id,
                content="Manual response awaiting the outbox.",
                expected_version=1,
                idempotency_key="control-integration-manual-1",
            )
            operator_message_id = operator_message.id
            operator_outbound_id = operator_outbound.message.id
            assert controlled.control_version == 1
            await db.commit()

        async with AsyncSessionLocal() as db:
            persisted_message = await db.get(ChatMessage, operator_message_id)
            persisted_outbound = await db.get(OutboundMessage, operator_outbound_id)
            persisted_control = await db.get(ChatConversation, conversation_id)
            event_count = (
                await db.execute(
                    select(func.count(ConversationControlEvent.id)).where(
                        ConversationControlEvent.conversation_id == conversation_id
                    )
                )
            ).scalar_one()
            assert persisted_message is not None
            assert persisted_message.status == "completed"
            assert persisted_message.metadata_json["control_version"] == 1
            assert persisted_outbound is not None
            assert persisted_outbound.status == "queued"
            assert persisted_outbound.sender_type == "operator"
            assert persisted_outbound.sender_admin_id == admin_id
            assert persisted_control is not None
            assert persisted_control.control_version == 1
            assert event_count == 1

        async with AsyncSessionLocal() as db:
            (
                _,
                duplicate_message,
                duplicate_outbound,
            ) = await service.record_operator_message(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
                actor_admin_id=admin_id,
                content="Manual response awaiting the outbox.",
                expected_version=1,
                idempotency_key="control-integration-manual-1",
            )
            assert duplicate_message.id == operator_message_id
            assert duplicate_outbound.message.id == operator_outbound_id
            assert duplicate_outbound.duplicate is True
            await db.commit()

        async with AsyncSessionLocal() as db:
            (
                _,
                rolled_back_message,
                rolled_back_outbound,
            ) = await service.record_operator_message(
                db,
                conversation_id=conversation_id,
                agent_id=agent_id,
                actor_admin_id=admin_id,
                content="This transaction will be rolled back.",
                expected_version=1,
                idempotency_key="control-integration-rollback",
            )
            rolled_back_message_id = rolled_back_message.id
            rolled_back_outbound_id = rolled_back_outbound.message.id
            await db.rollback()

        async with AsyncSessionLocal() as db:
            assert await db.get(ChatMessage, rolled_back_message_id) is None
            assert await db.get(OutboundMessage, rolled_back_outbound_id) is None

        async with AsyncSessionLocal() as db:
            legacy_conversation = ChatConversation(
                agent_id=agent_id,
                principal_id=principal_id,
                channel="web",
                external_thread_id=f"legacy-manual-{uuid4()}",
                route_key="legacy-manual-no-route",
                control_mode="human",
                control_version=0,
                assigned_admin_id=admin_id,
            )
            db.add(legacy_conversation)
            await db.commit()
            legacy_conversation_id = legacy_conversation.id

        async with AsyncSessionLocal() as db:
            with pytest.raises(
                OperatorMessagePersistenceError,
                match="explicit channel route",
            ):
                await service.record_operator_message(
                    db,
                    conversation_id=legacy_conversation_id,
                    agent_id=agent_id,
                    actor_admin_id=admin_id,
                    content="This message must fail closed.",
                    expected_version=0,
                    idempotency_key="legacy-route-missing",
                )
            await db.rollback()

        async with AsyncSessionLocal() as db:
            legacy_message_count = (
                await db.execute(
                    select(func.count(ChatMessage.id)).where(
                        ChatMessage.conversation_id == legacy_conversation_id
                    )
                )
            ).scalar_one()
            legacy_outbound_count = (
                await db.execute(
                    select(func.count(OutboundMessage.id)).where(
                        OutboundMessage.conversation_id == legacy_conversation_id
                    )
                )
            ).scalar_one()
            assert legacy_message_count == 0
            assert legacy_outbound_count == 0

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
                await db.execute(
                    delete(OutboundMessage).where(
                        OutboundMessage.conversation_id == conversation_id
                    )
                )
                await db.execute(delete(Principal).where(Principal.id == principal_id))
                if route_id is not None:
                    await db.execute(
                        delete(ChannelAgentRoute).where(
                            ChannelAgentRoute.id == route_id
                        )
                    )
                if connection_id is not None:
                    await db.execute(
                        delete(ChannelConnection).where(
                            ChannelConnection.id == connection_id
                        )
                    )
                await db.commit()
