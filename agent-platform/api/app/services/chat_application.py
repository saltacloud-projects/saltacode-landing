"""Channel-neutral conversation use case for trusted ingress adapters."""

from __future__ import annotations

import json
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
from app.services.agent_loop import AgentFile, run_agent_loop
from app.services.agent_runtime import (
    AgentRuntimeUnavailable,
    ResolvedAgentRuntime,
    agent_runtime_resolver,
)
from app.services.conversation_control import (
    AutomationBlockedError,
    ControlVersionConflictError,
    conversation_control_service,
)
from app.services.conversation_memory import conversation_memory_service
from app.services.outbound_delivery import (
    OutboundKind,
    OutboundSenderType,
    outbound_delivery_service,
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
    async def record_whatsapp_inbound(
        self,
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        request_id: str,
        content: str,
    ) -> ChatMessage:
        """Persist one provider inbound idempotently before automation starts."""
        message = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation.id,
                    ChatMessage.client_message_id == request_id,
                )
            )
        ).scalar_one_or_none()
        if message is not None:
            if message.role != "user":
                raise AgentNotReady("WhatsApp request id belongs to a non-user message")
            return message

        message = ChatMessage(
            conversation_id=conversation.id,
            client_message_id=request_id,
            role="user",
            content=content,
            status="completed",
            metadata_json={"origin": "channel_inbound"},
        )
        db.add(message)
        await db.flush()
        return message

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
        route_key: str | None = None,
        channel_route_id: uuid.UUID | None = None,
        control_version: int | None = None,
        outbound_files: list[AgentFile] | None = None,
        runtime: ResolvedAgentRuntime | None = None,
        redis=None,
    ) -> None:
        """Persist a WhatsApp exchange and its delivery commands atomically."""
        if await self._existing_outcome(db, request_id) is not None:
            return
        if route_key is None or channel_route_id is None:
            raise AgentNotReady("WhatsApp outbound requires an explicit route")
        route_scope = route_key or profile.slug
        identity = await self._resolve_identity(
            db, "whatsapp", route_scope, external_subject
        )
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
            route_key=route_scope,
            channel_route_id=channel_route_id,
        )
        inbound = await self.record_whatsapp_inbound(
            db,
            conversation=conversation,
            request_id=request_id,
            content=user_content,
        )
        inbound.content = user_content
        outbound = ChatMessage(
            conversation_id=conversation.id,
            client_message_id=f"{request_id}:assistant",
            role="assistant",
            content=assistant_content,
            status="completed",
            tool_names=list(tools_used),
            metadata_json={"origin": "automation"},
        )
        db.add(outbound)
        await db.flush()
        effective_control_version = (
            conversation.control_version if control_version is None else control_version
        )
        await self._enqueue_whatsapp_message(
            db,
            conversation=conversation,
            message=outbound,
            kind=OutboundKind.TEXT,
            payload={"text": assistant_content},
            control_version=effective_control_version,
            idempotency_key=f"whatsapp:{request_id}:assistant:text",
            correlation_id=request_id,
        )
        for index, agent_file in enumerate(outbound_files or []):
            await self._record_whatsapp_file(
                db,
                conversation=conversation,
                request_id=request_id,
                index=index,
                agent_file=agent_file,
                control_version=effective_control_version,
            )
        db.add(
            ChatExecution(
                request_id=request_id,
                conversation_id=conversation.id,
                inbound_message_id=inbound.id,
                output_message_id=outbound.id,
                status="completed",
                control_version=effective_control_version,
                tools_used=list(tools_used),
            )
        )
        await db.flush()
        await conversation_memory_service.refresh_summary(
            db, conversation=conversation, runtime=runtime
        )
        await self._invalidate_history(
            redis,
            conversation.id,
            runtime.config.history_message_limit if runtime else 20,
        )

    async def record_whatsapp_notification(
        self,
        db: AsyncSession,
        *,
        profile: AgentProfile,
        request_id: str,
        purpose: str,
        external_subject: str,
        content: str,
        route_key: str | None,
        channel_route_id: uuid.UUID | None,
        control_version: int,
    ) -> ChatMessage:
        """Persist one automated notification and delivery command atomically."""
        if route_key is None or channel_route_id is None:
            raise AgentNotReady("WhatsApp outbound requires an explicit route")
        identity = await self._resolve_identity(
            db,
            "whatsapp",
            route_key,
            external_subject,
        )
        conversation = await self._resolve_conversation(
            db,
            agent_id=profile.id,
            principal_id=identity.principal_id,
            channel="whatsapp",
            external_thread_id=external_subject,
            consent_version="whatsapp-existing-history-v1",
            route_key=route_key,
            channel_route_id=channel_route_id,
        )
        client_message_id = f"{request_id}:notification:{purpose}"
        message = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.conversation_id == conversation.id,
                    ChatMessage.client_message_id == client_message_id,
                )
            )
        ).scalar_one_or_none()
        if message is None:
            message = ChatMessage(
                conversation_id=conversation.id,
                client_message_id=client_message_id,
                role="assistant",
                content=content,
                status="completed",
                metadata_json={"origin": "automation", "purpose": purpose},
            )
            db.add(message)
            await db.flush()
        elif message.content != content:
            raise AgentNotReady(
                "notification idempotency key was reused with different content"
            )
        await self._enqueue_whatsapp_message(
            db,
            conversation=conversation,
            message=message,
            kind=OutboundKind.TEXT,
            payload={"text": content},
            control_version=control_version,
            idempotency_key=f"whatsapp:{request_id}:notification:{purpose}",
            correlation_id=request_id,
        )
        return message

    async def _record_whatsapp_file(
        self,
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        request_id: str,
        index: int,
        agent_file: AgentFile,
        control_version: int,
    ) -> None:
        if agent_file.storage_key is None:
            raise AgentNotReady("WhatsApp outbound files require durable storage")
        kind = (
            OutboundKind.IMAGE
            if agent_file.mime.startswith("image/")
            else OutboundKind.DOCUMENT
        )
        message = ChatMessage(
            conversation_id=conversation.id,
            client_message_id=f"{request_id}:assistant:file:{index}",
            role="assistant",
            content=f"[{kind.value}: {agent_file.name}]",
            status="completed",
            metadata_json={
                "origin": "automation",
                "attachment": {
                    "storage_key": agent_file.storage_key,
                    "name": agent_file.name,
                    "mime": agent_file.mime,
                },
            },
        )
        db.add(message)
        await db.flush()
        await self._enqueue_whatsapp_message(
            db,
            conversation=conversation,
            message=message,
            kind=kind,
            payload={
                "storage_key": agent_file.storage_key,
                "name": agent_file.name,
                "mime": agent_file.mime,
            },
            control_version=control_version,
            idempotency_key=f"whatsapp:{request_id}:assistant:file:{index}",
            correlation_id=request_id,
        )

    @staticmethod
    async def _enqueue_whatsapp_message(
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        message: ChatMessage,
        kind: OutboundKind,
        payload: dict,
        control_version: int,
        idempotency_key: str,
        correlation_id: str,
    ) -> None:
        await outbound_delivery_service.enqueue(
            db,
            conversation_id=conversation.id,
            agent_id=conversation.agent_id,
            chat_message_id=message.id,
            kind=kind,
            payload=payload,
            sender_type=OutboundSenderType.AUTOMATION,
            control_version=control_version,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    async def load_whatsapp_context(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        external_subject: str,
        limit: int,
        route_key: str,
        channel_route_id: uuid.UUID,
        history_cache_ttl_seconds: int = 0,
        redis=None,
    ) -> tuple[list[dict[str, str]], str | None, ChatConversation]:
        """Load only the neutral conversation owned by this agent and route."""
        conversation = (
            await db.execute(
                select(ChatConversation).where(
                    ChatConversation.agent_id == agent_id,
                    ChatConversation.channel == "whatsapp",
                    ChatConversation.route_key == route_key,
                    ChatConversation.external_thread_id == external_subject,
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            identity = await self._resolve_identity(
                db,
                "whatsapp",
                route_key,
                external_subject,
            )
            conversation = await self._resolve_conversation(
                db,
                agent_id=agent_id,
                principal_id=identity.principal_id,
                channel="whatsapp",
                external_thread_id=external_subject,
                consent_version="whatsapp-existing-history-v1",
                route_key=route_key,
                channel_route_id=channel_route_id,
            )
        if conversation.channel_route_id not in (None, channel_route_id):
            raise AgentNotReady("WhatsApp identity belongs to another route")
        return (
            await self._history(
                db,
                conversation.id,
                limit,
                redis=redis,
                cache_ttl_seconds=history_cache_ttl_seconds,
            ),
            conversation.summary,
            conversation,
        )

    async def execute_web(
        self,
        db: AsyncSession,
        request: InternalExecutionRequest,
        redis=None,
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
                            ChannelIdentity.route_key == conversation.route_key,
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
            execution.control_version = conversation.control_version
            history = await self._history(
                db,
                conversation.id,
                runtime.config.history_message_limit if runtime else 20,
                redis=redis,
                cache_ttl_seconds=(
                    runtime.config.history_cache_ttl_seconds if runtime else 0
                ),
            )
            await db.commit()
        else:
            profile = resolved_profile

            route_scope = request.route_key or profile.slug
            identity = await self._resolve_identity(
                db, "web", route_scope, str(request.session_id)
            )
            conversation = await self._resolve_conversation(
                db,
                agent_id=profile.id,
                principal_id=identity.principal_id,
                channel="web",
                external_thread_id=str(request.session_id),
                consent_version=request.consent.version,
                route_key=route_scope,
                channel_route_id=resolved_route.route.id if resolved_route else None,
            )
            history = await self._history(
                db,
                conversation.id,
                runtime.config.history_message_limit if runtime else 20,
                redis=redis,
                cache_ttl_seconds=(
                    runtime.config.history_cache_ttl_seconds if runtime else 0
                ),
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
                control_version=conversation.control_version,
            )
            db.add(execution)
            await db.commit()

        started = time.monotonic()

        async def automation_guard() -> None:
            await conversation_control_service.assert_automation_allowed(
                db,
                conversation_id=conversation.id,
                agent_id=profile.id,
                expected_version=execution.control_version,
            )

        try:
            await automation_guard()
        except (AutomationBlockedError, ControlVersionConflictError) as exc:
            await self._mark_execution_control_blocked(
                db,
                inbound,
                execution,
                started=started,
            )
            raise AgentNotReady("conversation automation is not active") from exc

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
                automation_guard=automation_guard,
            )
            await conversation_control_service.assert_automation_allowed(
                db,
                conversation_id=conversation.id,
                agent_id=profile.id,
                expected_version=execution.control_version,
                for_update=True,
            )
        except (AutomationBlockedError, ControlVersionConflictError) as exc:
            await self._mark_execution_control_blocked(
                db,
                inbound,
                execution,
                started=started,
            )
            raise AgentNotReady(
                "conversation automation changed during execution"
            ) from exc
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
        await self._invalidate_history(
            redis,
            conversation.id,
            runtime.config.history_message_limit if runtime else 20,
        )
        if await conversation_memory_service.refresh_summary(
            db, conversation=conversation, runtime=runtime
        ):
            await db.commit()
        return ExecutionOutcome(
            output=result.response_text, tools_used=tuple(result.tools_used)
        )

    @staticmethod
    async def _mark_execution_control_blocked(
        db: AsyncSession,
        inbound: ChatMessage,
        execution: ChatExecution,
        *,
        started: float,
    ) -> None:
        inbound.status = "completed"
        execution.status = "blocked"
        execution.error_code = "conversation_control_changed"
        execution.duration_ms = int((time.monotonic() - started) * 1000)
        await db.commit()

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
        route_key: str,
        external_subject: str,
    ) -> ChannelIdentity:
        identity = (
            await db.execute(
                select(ChannelIdentity).where(
                    ChannelIdentity.channel == channel,
                    ChannelIdentity.route_key == route_key,
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
            route_key=route_key,
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
        route_key: str,
        channel_route_id: uuid.UUID | None = None,
    ) -> ChatConversation:
        conversation = (
            await db.execute(
                select(ChatConversation).where(
                    ChatConversation.agent_id == agent_id,
                    ChatConversation.channel == channel,
                    ChatConversation.route_key == route_key,
                    ChatConversation.external_thread_id == external_thread_id,
                )
            )
        ).scalar_one_or_none()
        if conversation is not None:
            if channel_route_id is not None and conversation.channel_route_id not in (
                None,
                channel_route_id,
            ):
                raise AgentNotReady("session is already associated with another route")
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
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
        limit: int = 20,
        *,
        redis=None,
        cache_ttl_seconds: int = 0,
    ) -> list[dict[str, str]]:
        if limit <= 0:
            return []
        cache_key = self._history_cache_key(conversation_id, limit)
        if redis is not None and cache_ttl_seconds > 0:
            try:
                cached = await redis.get(cache_key)
                if cached:
                    payload = json.loads(cached)
                    if self._is_history_payload(payload):
                        return payload
            except Exception as exc:
                logger.warning(
                    "conversation_history_cache_read_failed",
                    extra={"conversation_id": str(conversation_id), "error": str(exc)},
                )
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
        history = [{"role": row.role, "content": row.content} for row in rows]
        if redis is not None and cache_ttl_seconds > 0:
            try:
                await redis.setex(
                    cache_key,
                    cache_ttl_seconds,
                    json.dumps(history, ensure_ascii=False),
                )
            except Exception as exc:
                logger.warning(
                    "conversation_history_cache_write_failed",
                    extra={"conversation_id": str(conversation_id), "error": str(exc)},
                )
        return history

    @staticmethod
    def _history_cache_key(conversation_id: uuid.UUID, limit: int) -> str:
        return f"chat-history:{conversation_id}:{limit}"

    @staticmethod
    def _is_history_payload(payload) -> bool:
        return isinstance(payload, list) and all(
            isinstance(item, dict)
            and item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
            for item in payload
        )

    async def _invalidate_history(
        self, redis, conversation_id: uuid.UUID, limit: int
    ) -> None:
        if redis is None:
            return
        try:
            await redis.delete(self._history_cache_key(conversation_id, limit))
        except Exception as exc:
            logger.warning(
                "conversation_history_cache_invalidation_failed",
                extra={"conversation_id": str(conversation_id), "error": str(exc)},
            )


chat_application_service = ChatApplicationService()
