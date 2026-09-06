"""PostgreSQL coverage for scoped and idempotent quote contact requests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.conversation_event import ConversationEvent
from app.models.platform import ChatConversation, Principal
from app.schemas.tools import ToolExecutionContext
from app.services.tools.adapters.commercial_quote_contact_request import (
    CommercialQuoteContactRequestTool,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _CommercialGraph:
    agent_id: UUID
    other_agent_id: UUID
    principal_id: UUID
    other_principal_id: UUID
    web_conversation_id: UUID
    whatsapp_conversation_id: UUID
    human_conversation_id: UUID
    web_subject: str
    whatsapp_subject: str


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.fixture
async def commercial_graph() -> _CommercialGraph:
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        agent = _agent(f"quote-contact-{suffix}")
        other_agent = _agent(f"quote-contact-other-{suffix}")
        principal = Principal(display_name="Quote contact")
        other_principal = Principal(display_name="Other quote contact")
        db.add_all([agent, other_agent, principal, other_principal])
        await db.flush()

        web_subject = f"web-{suffix}"
        whatsapp_subject = f"wa-{suffix}"
        web_conversation = ChatConversation(
            agent_id=agent.id,
            principal_id=principal.id,
            channel="web",
            external_thread_id=web_subject,
            route_key=f"web-route-{suffix}",
        )
        whatsapp_conversation = ChatConversation(
            agent_id=agent.id,
            principal_id=principal.id,
            channel="whatsapp",
            external_thread_id=whatsapp_subject,
            route_key=f"whatsapp-route-{suffix}",
        )
        human_conversation = ChatConversation(
            agent_id=agent.id,
            principal_id=principal.id,
            channel="web",
            external_thread_id=f"human-{suffix}",
            route_key=f"human-route-{suffix}",
            control_mode="paused",
        )
        db.add_all([web_conversation, whatsapp_conversation, human_conversation])
        await db.commit()
        graph = _CommercialGraph(
            agent_id=agent.id,
            other_agent_id=other_agent.id,
            principal_id=principal.id,
            other_principal_id=other_principal.id,
            web_conversation_id=web_conversation.id,
            whatsapp_conversation_id=whatsapp_conversation.id,
            human_conversation_id=human_conversation.id,
            web_subject=web_subject,
            whatsapp_subject=whatsapp_subject,
        )

    try:
        yield graph
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ChatConversation).where(
                    ChatConversation.id.in_(
                        [
                            graph.web_conversation_id,
                            graph.whatsapp_conversation_id,
                            graph.human_conversation_id,
                        ]
                    )
                )
            )
            await db.execute(
                delete(Principal).where(
                    Principal.id.in_([graph.principal_id, graph.other_principal_id])
                )
            )
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_([graph.agent_id, graph.other_agent_id])
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_web_request_publishes_one_safe_public_event(commercial_graph) -> None:
    tool = CommercialQuoteContactRequestTool()
    context = _context(
        graph=commercial_graph,
        channel="web",
        conversation_id=commercial_graph.web_conversation_id,
        external_subject=commercial_graph.web_subject,
    )
    params = {
        "title": "  Website\u0000 quote ",
        "summary": "Contact lead@example.com or +54 9 387 555-1212 about a site.",
        "preferred_delivery_channel": "email",
    }

    first, duplicate = await asyncio.gather(
        tool.invoke(params, context.request_id, context),
        tool.invoke(
            {
                "title": "Website quote",
                "summary": "Contact [redacted] or [redacted] about a site.",
                "preferred_delivery_channel": " EMAIL ",
            },
            context.request_id,
            context,
        ),
    )
    changed_duplicate = await tool.invoke(
        {**params, "preferred_delivery_channel": "whatsapp"},
        context.request_id,
        context,
    )

    assert first.status == "success"
    assert duplicate.status == "success"
    assert duplicate.result == first.result
    assert changed_duplicate.status == "error"
    assert "conflicts" in (changed_duplicate.error or "")
    assert first.result["action"] == "show_contact_form"
    assert first.result["consent_status"] == "not_captured"

    async with AsyncSessionLocal() as db:
        events = (
            (
                await db.execute(
                    select(ConversationEvent).where(
                        ConversationEvent.conversation_id
                        == commercial_graph.web_conversation_id,
                        ConversationEvent.event_type == "commercial.contact.requested",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1
    assert events[0].visibility == "public"
    assert events[0].payload_json == {
        "request_id": context.request_id,
        "title": "Website quote",
        "summary": "Contact [redacted] or [redacted] about a site.",
        "preferred_delivery_channel": "email",
    }


@pytest.mark.asyncio
async def test_scope_and_human_control_block_event_publication(
    commercial_graph,
) -> None:
    tool = CommercialQuoteContactRequestTool()
    params = {
        "title": "Website quote",
        "summary": "A public website for a local business.",
        "preferred_delivery_channel": "email",
    }
    wrong_principal = _context(
        graph=commercial_graph,
        channel="web",
        conversation_id=commercial_graph.web_conversation_id,
        principal_id=commercial_graph.other_principal_id,
        external_subject=commercial_graph.web_subject,
        request_id="quote-wrong-principal",
    )
    wrong_agent = _context(
        graph=commercial_graph,
        channel="web",
        conversation_id=commercial_graph.web_conversation_id,
        agent_id=commercial_graph.other_agent_id,
        external_subject=commercial_graph.web_subject,
        request_id="quote-wrong-agent",
    )
    human_control = _context(
        graph=commercial_graph,
        channel="web",
        conversation_id=commercial_graph.human_conversation_id,
        external_subject=None,
        request_id="quote-human-control",
    )

    wrong_result = await tool.invoke(
        params,
        wrong_principal.request_id,
        wrong_principal,
    )
    wrong_agent_result = await tool.invoke(
        params,
        wrong_agent.request_id,
        wrong_agent,
    )
    human_result = await tool.invoke(
        params,
        human_control.request_id,
        human_control,
    )

    assert wrong_result.status == "error"
    assert wrong_agent_result.status == "error"
    assert human_result.status == "error"
    async with AsyncSessionLocal() as db:
        event_count = len(
            (
                (
                    await db.execute(
                        select(ConversationEvent).where(
                            ConversationEvent.conversation_id.in_(
                                [
                                    commercial_graph.web_conversation_id,
                                    commercial_graph.human_conversation_id,
                                ]
                            ),
                            ConversationEvent.event_type
                            == "commercial.contact.requested",
                        )
                    )
                )
                .scalars()
                .all()
            )
        )
    assert event_count == 0


@pytest.mark.asyncio
async def test_whatsapp_returns_collection_instructions_without_event(
    commercial_graph,
) -> None:
    tool = CommercialQuoteContactRequestTool()
    context = _context(
        graph=commercial_graph,
        channel="whatsapp",
        conversation_id=commercial_graph.whatsapp_conversation_id,
        external_subject=commercial_graph.whatsapp_subject,
        request_id="quote-whatsapp",
    )

    result = await tool.invoke(
        {
            "title": "ERP quote",
            "summary": "The company needs process automation.",
            "preferred_delivery_channel": "whatsapp",
        },
        context.request_id,
        context,
    )

    assert result.status == "success"
    assert result.result["action"] == "request_contact_details_and_consent"
    assert result.result["consent_status"] == "not_captured"
    async with AsyncSessionLocal() as db:
        event = (
            await db.execute(
                select(ConversationEvent).where(
                    ConversationEvent.conversation_id
                    == commercial_graph.whatsapp_conversation_id,
                    ConversationEvent.event_type == "commercial.contact.requested",
                )
            )
        ).scalar_one_or_none()
    assert event is None


def _context(
    *,
    graph: _CommercialGraph,
    channel: str,
    conversation_id: UUID,
    external_subject: str | None,
    principal_id: UUID | None = None,
    agent_id: UUID | None = None,
    request_id: str = "quote-web",
) -> ToolExecutionContext:
    return ToolExecutionContext(
        request_id=request_id,
        channel=channel,
        principal_id=str(principal_id or graph.principal_id),
        conversation_id=str(conversation_id),
        agent_id=str(agent_id or graph.agent_id),
        external_subject=external_subject,
    )


def _agent(slug: str) -> AgentProfile:
    return AgentProfile(
        name="Quote contact integration agent",
        slug=slug,
        version=1,
        is_active=True,
        is_public=True,
        retention_days=30,
        prompt_identity="test",
        prompt_domain="test",
        prompt_guardrails="test",
        unauthorized_message="unauthorized",
        error_message="error",
    )
