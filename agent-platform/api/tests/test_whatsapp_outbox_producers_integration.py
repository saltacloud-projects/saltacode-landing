"""PostgreSQL integration coverage for WhatsApp outbound producers."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.outbound import OutboundMessage
from app.models.platform import ChannelIdentity, ChatExecution, ChatMessage, Principal
from app.services.agent_loop import AgentFile
from app.services.chat_application import AgentNotReady, ChatApplicationService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_whatsapp_exchange_and_commands_are_atomic_and_idempotent():
    service = ChatApplicationService()
    connection_id = None
    route_id = None
    principal_id = None
    request_id = str(uuid4())
    rollback_request_id = str(uuid4())
    in_memory_request_id = str(uuid4())

    try:
        async with AsyncSessionLocal() as db:
            profile = (
                (
                    await db.execute(
                        select(AgentProfile).where(AgentProfile.is_active.is_(True))
                    )
                )
                .scalars()
                .first()
            )
            assert profile is not None
            connection = ChannelConnection(
                name="WhatsApp producer integration connection",
                slug=f"whatsapp-producer-{uuid4().hex}",
                channel="whatsapp",
                external_account_id=f"producer-account-{uuid4().hex}",
                settings_json={},
                is_active=True,
            )
            db.add(connection)
            await db.flush()
            route = ChannelAgentRoute(
                channel="whatsapp",
                route_key=f"producer-route-{uuid4().hex}",
                channel_connection_id=connection.id,
                agent_id=profile.id,
                is_active=True,
            )
            db.add(route)
            await db.commit()
            connection_id = connection.id
            route_id = route.id
            route_key = route.route_key

        async with AsyncSessionLocal() as db:
            await service.record_whatsapp_exchange(
                db,
                profile=profile,
                request_id=request_id,
                external_subject="5493870000000",
                user_content="Please send the proposal.",
                assistant_content="I attached the proposal.",
                tools_used=["proposal_builder"],
                route_key=route_key,
                channel_route_id=route_id,
                control_version=0,
                outbound_files=[
                    AgentFile(
                        name="proposal.pdf",
                        mime="application/pdf",
                        storage_key="blobs/ab/proposal.pdf",
                    )
                ],
            )
            await db.commit()

            execution = (
                await db.execute(
                    select(ChatExecution).where(ChatExecution.request_id == request_id)
                )
            ).scalar_one()
            conversation_id = execution.conversation_id
            identity = (
                await db.execute(
                    select(ChannelIdentity).where(
                        ChannelIdentity.channel == "whatsapp",
                        ChannelIdentity.route_key == route_key,
                        ChannelIdentity.external_subject == "5493870000000",
                    )
                )
            ).scalar_one()
            principal_id = identity.principal_id

        async with AsyncSessionLocal() as db:
            messages = list(
                (
                    await db.execute(
                        select(ChatMessage)
                        .where(ChatMessage.conversation_id == conversation_id)
                        .order_by(ChatMessage.client_message_id)
                    )
                )
                .scalars()
                .all()
            )
            outbound = list(
                (
                    await db.execute(
                        select(OutboundMessage)
                        .where(OutboundMessage.conversation_id == conversation_id)
                        .order_by(OutboundMessage.sequence)
                    )
                )
                .scalars()
                .all()
            )
            assert len(messages) == 3
            assert all(message.status == "completed" for message in messages)
            assert [message.kind for message in outbound] == ["text", "document"]
            assert [message.status for message in outbound] == ["queued", "queued"]
            assert outbound[1].payload_json == {
                "storage_key": "blobs/ab/proposal.pdf",
                "name": "proposal.pdf",
                "mime": "application/pdf",
            }

        async with AsyncSessionLocal() as db:
            await service.record_whatsapp_exchange(
                db,
                profile=profile,
                request_id=request_id,
                external_subject="5493870000000",
                user_content="Please send the proposal.",
                assistant_content="I attached the proposal.",
                tools_used=["proposal_builder"],
                route_key=route_key,
                channel_route_id=route_id,
                control_version=0,
                outbound_files=[
                    AgentFile(
                        name="proposal.pdf",
                        mime="application/pdf",
                        storage_key="blobs/ab/proposal.pdf",
                    )
                ],
            )
            await db.commit()
            message_count = (
                await db.execute(
                    select(func.count(ChatMessage.id)).where(
                        ChatMessage.conversation_id == conversation_id
                    )
                )
            ).scalar_one()
            outbound_count = (
                await db.execute(
                    select(func.count(OutboundMessage.id)).where(
                        OutboundMessage.conversation_id == conversation_id
                    )
                )
            ).scalar_one()
            assert message_count == 3
            assert outbound_count == 2

        async with AsyncSessionLocal() as db:
            await service.record_whatsapp_exchange(
                db,
                profile=profile,
                request_id=rollback_request_id,
                external_subject="5493870000000",
                user_content="This transaction will roll back.",
                assistant_content="This response must not persist.",
                tools_used=[],
                route_key=route_key,
                channel_route_id=route_id,
                control_version=0,
            )
            await db.rollback()

        async with AsyncSessionLocal() as db:
            assert (
                await db.execute(
                    select(ChatExecution).where(
                        ChatExecution.request_id == rollback_request_id
                    )
                )
            ).scalar_one_or_none() is None
            assert (
                await db.execute(
                    select(OutboundMessage).where(
                        OutboundMessage.idempotency_key
                        == f"whatsapp:{rollback_request_id}:assistant:text"
                    )
                )
            ).scalar_one_or_none() is None
            rolled_back_message_count = (
                await db.execute(
                    select(func.count(ChatMessage.id)).where(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.client_message_id.like(f"{rollback_request_id}%"),
                    )
                )
            ).scalar_one()
            assert rolled_back_message_count == 0

        async with AsyncSessionLocal() as db:
            with pytest.raises(AgentNotReady, match="durable storage"):
                await service.record_whatsapp_exchange(
                    db,
                    profile=profile,
                    request_id=in_memory_request_id,
                    external_subject="5493870000000",
                    user_content="Generate an in-memory file.",
                    assistant_content="The file is ready.",
                    tools_used=[],
                    route_key=route_key,
                    channel_route_id=route_id,
                    control_version=0,
                    outbound_files=[
                        AgentFile(
                            name="temporary.pdf",
                            mime="application/pdf",
                            content=b"not-durable",
                        )
                    ],
                )
            await db.rollback()

        async with AsyncSessionLocal() as db:
            in_memory_message_count = (
                await db.execute(
                    select(func.count(ChatMessage.id)).where(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.client_message_id.like(f"{in_memory_request_id}%"),
                    )
                )
            ).scalar_one()
            in_memory_outbound_count = (
                await db.execute(
                    select(func.count(OutboundMessage.id)).where(
                        OutboundMessage.conversation_id == conversation_id,
                        OutboundMessage.idempotency_key.like(
                            f"whatsapp:{in_memory_request_id}:%"
                        ),
                    )
                )
            ).scalar_one()
            assert in_memory_message_count == 0
            assert in_memory_outbound_count == 0
    finally:
        await engine.dispose()
        async with AsyncSessionLocal() as db:
            if principal_id is not None:
                await db.execute(delete(Principal).where(Principal.id == principal_id))
            if route_id is not None:
                await db.execute(
                    delete(ChannelAgentRoute).where(ChannelAgentRoute.id == route_id)
                )
            if connection_id is not None:
                await db.execute(
                    delete(ChannelConnection).where(
                        ChannelConnection.id == connection_id
                    )
                )
            await db.commit()
        await engine.dispose()
