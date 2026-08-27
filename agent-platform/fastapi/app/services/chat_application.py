"""Channel-neutral conversation use case for trusted ingress adapters."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent_profile import AgentProfile
from app.models.platform import (
    ChannelIdentity,
    ChatConversation,
    ChatExecution,
    ChatMessage,
    Principal,
)
from app.models.tool_config import ToolConfig
from app.schemas.executions import InternalExecutionRequest
from app.schemas.tools import ToolExecutionContext
from app.services.agent_loop import run_agent_loop
from app.services.agent_runtime import (
    AgentRuntimeUnavailable,
    ResolvedAgentRuntime,
    agent_runtime_resolver,
)
from app.services.tool_policy import tool_policy_service
from app.services.tools.registry import tool_registry

logger = logging.getLogger(__name__)


class AgentNotReady(RuntimeError):
    pass


class ExecutionInProgress(RuntimeError):
    pass


class TranscriptConsentRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionOutcome:
    output: str
    tools_used: tuple[str, ...]


class ChatApplicationService:
    async def record_whatsapp_exchange(
        self,
        db: AsyncSession,
        *,
        profile: AgentProfile,
        request_id: str,
        external_subject: str,
        user_content: str,
        assistant_content: str,
        tools_used: list[str],
        display_name: str | None = None,
    ) -> None:
        """Dual-write the existing WhatsApp flow into the neutral history."""
        if await self._existing_outcome(db, request_id) is not None:
            return
        identity = await self._resolve_identity(db, "whatsapp", external_subject)
        if display_name:
            principal = await db.get(Principal, identity.principal_id)
            if principal is not None:
                principal.display_name = display_name
                principal.kind = "verified"
        conversation = await self._resolve_conversation(
            db,
            agent_id=profile.id,
            principal_id=identity.principal_id,
            channel="whatsapp",
            external_thread_id=external_subject,
            consent_version="whatsapp-existing-history-v1",
        )
        inbound = ChatMessage(
            conversation_id=conversation.id,
            client_message_id=request_id,
            role="user",
            content=user_content,
            status="completed",
        )
        outbound = ChatMessage(
            conversation_id=conversation.id,
            client_message_id=f"{request_id}:assistant",
            role="assistant",
            content=assistant_content,
            status="completed",
            tool_names=list(tools_used),
        )
        db.add_all([inbound, outbound])
        await db.flush()
        db.add(
            ChatExecution(
                request_id=request_id,
                conversation_id=conversation.id,
                inbound_message_id=inbound.id,
                output_message_id=outbound.id,
                status="completed",
                tools_used=list(tools_used),
            )
        )

    async def execute_web(
        self,
        db: AsyncSession,
        request: InternalExecutionRequest,
    ) -> ExecutionOutcome:
        if not request.consent.granted:
            raise TranscriptConsentRequired(
                "transcript consent is required for conversation history"
            )

        existing_execution = (
            await db.execute(
                select(ChatExecution).where(
                    ChatExecution.request_id == str(request.request_id)
                )
            )
        ).scalar_one_or_none()
        runtime: ResolvedAgentRuntime | None = None
        resolved_route = None
        if request.route_key is not None:
            try:
                resolved_route = await agent_runtime_resolver.resolve_route(
                    db, "web", request.route_key, require_public=True
                )
            except AgentRuntimeUnavailable as exc:
                raise AgentNotReady(str(exc)) from exc
            runtime = resolved_route.runtime
            resolved_profile = runtime.profile
        else:
            logger.warning("legacy_web_execution_without_route_key")
            resolved_profile = (
                await db.execute(
                    select(AgentProfile).where(
                        AgentProfile.slug == settings.default_agent_slug,
                        AgentProfile.is_active == True,  # noqa: E712
                        AgentProfile.is_public == True,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
            if resolved_profile is None:
                raise AgentNotReady("the public agent profile is not active")
            try:
                runtime = await agent_runtime_resolver.resolve_agent(
                    db, resolved_profile.id, require_public=True
                )
                resolved_profile = runtime.profile
            except AgentRuntimeUnavailable:
                logger.warning("legacy_default_agent_runtime_unavailable")

        if existing_execution is not None:
            inbound = await db.get(ChatMessage, existing_execution.inbound_message_id)
            if inbound is None or inbound.content != request.input:
                raise AgentNotReady("request id was already used with different input")
            execution = existing_execution
            conversation = await db.get(ChatConversation, execution.conversation_id)
            if conversation is None:
                raise AgentNotReady("the stored conversation is unavailable")
            if conversation.agent_id != resolved_profile.id:
                raise AgentNotReady("request id was already used on another route")
            if request.route_key is not None and (
                conversation.route_key != request.route_key
                or conversation.channel_route_id != resolved_route.route.id
            ):
                raise AgentNotReady("request id was already used on another route")
            identity = (
                (
                    await db.execute(
                        select(ChannelIdentity).where(
                            ChannelIdentity.principal_id == conversation.principal_id,
                            ChannelIdentity.channel == "web",
                        )
                    )
                )
                .scalars()
                .first()
            )
            if identity is None:
                raise AgentNotReady("the stored channel identity is unavailable")
            if identity.external_subject != str(request.session_id):
                raise AgentNotReady("request id was already used by another session")
            if existing_execution.status == "completed":
                existing = await self._existing_outcome(db, str(request.request_id))
                if existing is None:
                    raise AgentNotReady("the stored execution outcome is unavailable")
                return existing
            if existing_execution.status == "running":
                raise ExecutionInProgress("this execution is already in progress")
            inbound.status = "accepted"
            existing_execution.status = "running"
            existing_execution.error_code = None
            profile = resolved_profile
            conversation.transcript_consent = True
            conversation.consent_version = request.consent.version
            history = await self._history(
                db,
                conversation.id,
                runtime.config.history_message_limit if runtime else 20,
            )
            await db.commit()
        else:
            profile = resolved_profile

            identity = await self._resolve_identity(db, "web", str(request.session_id))
            conversation = await self._resolve_conversation(
                db,
                agent_id=profile.id,
                principal_id=identity.principal_id,
                channel="web",
                external_thread_id=str(request.session_id),
                consent_version=request.consent.version,
                route_key=request.route_key,
                channel_route_id=resolved_route.route.id if resolved_route else None,
            )
            history = await self._history(
                db,
                conversation.id,
                runtime.config.history_message_limit if runtime else 20,
            )

            inbound = ChatMessage(
                conversation_id=conversation.id,
                client_message_id=str(request.request_id),
                role="user",
                content=request.input,
                status="accepted",
                metadata_json={"locale": request.locale},
            )
            db.add(inbound)
            await db.flush()
            execution = ChatExecution(
                request_id=str(request.request_id),
                conversation_id=conversation.id,
                inbound_message_id=inbound.id,
                status="running",
            )
            db.add(execution)
            await db.commit()

        context = ToolExecutionContext(
            request_id=str(request.request_id),
            channel="web",
            principal_id=str(identity.principal_id),
            conversation_id=str(conversation.id),
            agent_id=str(profile.id),
            external_subject=str(request.session_id),
            scopes=set(),
        )
        available_tools = await tool_policy_service.available_tools(
            db, context, set(tool_registry.list_tools())
        )
        names = [item["tool_name"] for item in available_tools]
        configs = (
            {
                item.tool_name: {
                    "params_schema": item.params_schema or {},
                    "timeout_seconds": item.timeout_seconds,
                }
                for item in (
                    await db.execute(
                        select(ToolConfig).where(ToolConfig.tool_name.in_(names))
                    )
                )
                .scalars()
                .all()
            }
            if names
            else {}
        )

        started = time.monotonic()
        try:
            result = await run_agent_loop(
                user_message=request.input,
                conversation_history=history,
                available_tools=available_tools,
                tool_configs=configs,
                profile=profile,
                user_id=None,
                phone=str(request.session_id),
                request_id=str(request.request_id),
                db=db,
                conversation_summary=conversation.summary,
                rag_area_ids_override=set(),
                execution_context=context,
                runtime=runtime,
            )
        except Exception:
            execution.status = "failed"
            execution.error_code = "agent_execution_exception"
            execution.duration_ms = int((time.monotonic() - started) * 1000)
            await db.commit()
            raise
        if result.status != "success" or not result.response_text:
            execution.status = "failed"
            execution.error_code = "agent_execution_failed"
            execution.duration_ms = int((time.monotonic() - started) * 1000)
            await db.commit()
            raise AgentNotReady("the agent could not complete this execution")

        outbound = ChatMessage(
            conversation_id=conversation.id,
            client_message_id=f"{request.request_id}:assistant",
            role="assistant",
            content=result.response_text,
            status="completed",
            tool_names=list(result.tools_used),
        )
        inbound.status = "completed"
        db.add(outbound)
        await db.flush()
        execution.status = "completed"
        execution.output_message_id = outbound.id
        execution.tools_used = list(result.tools_used)
        execution.duration_ms = int((time.monotonic() - started) * 1000)
        await db.commit()
        return ExecutionOutcome(
            output=result.response_text, tools_used=tuple(result.tools_used)
        )

    async def _existing_outcome(
        self, db: AsyncSession, request_id: str
    ) -> ExecutionOutcome | None:
        row = (
            await db.execute(
                select(ChatExecution, ChatMessage)
                .join(ChatMessage, ChatExecution.output_message_id == ChatMessage.id)
                .where(
                    ChatExecution.request_id == request_id,
                    ChatExecution.status == "completed",
                )
            )
        ).one_or_none()
        if row is None:
            return None
        execution, message = row
        return ExecutionOutcome(
            output=message.content, tools_used=tuple(execution.tools_used or [])
        )

    async def _resolve_identity(
        self,
        db: AsyncSession,
        channel: str,
        external_subject: str,
    ) -> ChannelIdentity:
        identity = (
            await db.execute(
                select(ChannelIdentity).where(
                    ChannelIdentity.channel == channel,
                    ChannelIdentity.external_subject == external_subject,
                )
            )
        ).scalar_one_or_none()
        if identity is not None:
            return identity
        principal = Principal(kind="anonymous", is_active=True)
        db.add(principal)
        await db.flush()
        identity = ChannelIdentity(
            principal_id=principal.id,
            channel=channel,
            external_subject=external_subject,
            verified=True,
        )
        db.add(identity)
        await db.flush()
        return identity

    async def _resolve_conversation(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        principal_id: uuid.UUID,
        channel: str,
        external_thread_id: str,
        consent_version: str,
        route_key: str | None = None,
        channel_route_id: uuid.UUID | None = None,
    ) -> ChatConversation:
        conversation = (
            await db.execute(
                select(ChatConversation).where(
                    ChatConversation.agent_id == agent_id,
                    ChatConversation.channel == channel,
                    ChatConversation.external_thread_id == external_thread_id,
                )
            )
        ).scalar_one_or_none()
        if conversation is not None:
            if route_key is not None and conversation.route_key not in (
                None,
                route_key,
            ):
                raise AgentNotReady("session is already associated with another route")
            if channel_route_id is not None and conversation.channel_route_id not in (
                None,
                channel_route_id,
            ):
                raise AgentNotReady("session is already associated with another route")
            conversation.route_key = route_key or conversation.route_key
            conversation.channel_route_id = (
                channel_route_id or conversation.channel_route_id
            )
            conversation.transcript_consent = True
            conversation.consent_version = consent_version
            return conversation
        conversation = ChatConversation(
            agent_id=agent_id,
            principal_id=principal_id,
            channel=channel,
            external_thread_id=external_thread_id,
            transcript_consent=True,
            consent_version=consent_version,
            route_key=route_key,
            channel_route_id=channel_route_id,
        )
        db.add(conversation)
        await db.flush()
        return conversation

    async def _history(
        self, db: AsyncSession, conversation_id: uuid.UUID, limit: int = 20
    ) -> list[dict[str, str]]:
        rows = list(
            (
                await db.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.conversation_id == conversation_id,
                        ChatMessage.status == "completed",
                    )
                    .order_by(ChatMessage.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        rows.reverse()
        return [{"role": row.role, "content": row.content} for row in rows]


chat_application_service = ChatApplicationService()
