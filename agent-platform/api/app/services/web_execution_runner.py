"""Execute one durable web-chat claim through the existing agent policies."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models.platform import ChatConversation, ChatMessage
from app.models.tool_config import ToolConfig
from app.schemas.tools import ToolExecutionContext
from app.services.agent_loop import AgentLoopResult, run_agent_loop
from app.services.agent_runtime import (
    AgentRuntimeResolver,
    AgentRuntimeUnavailable,
    ResolvedAgentRuntime,
    agent_runtime_resolver,
)
from app.services.conversation_control import (
    AutomationBlockedError,
    ControlVersionConflictError,
    conversation_control_service,
)
from app.services.tool_policy import ToolPolicyService, tool_policy_service
from app.services.tools.registry import tool_registry
from app.services.web_execution_queue import (
    ClaimedWebExecution,
    RecordedWebExecutionOutcome,
    WebExecutionAutomationBlockedError,
    WebExecutionClaimOwnershipError,
    WebExecutionLeaseExpiredError,
    WebExecutionOutcome,
    WebExecutionQueueService,
    web_execution_queue_service,
)

logger = logging.getLogger(__name__)
AgentLoop = Callable[..., Awaitable[AgentLoopResult]]


class WebExecutionRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CLAIM_LOST = "claim_lost"


@dataclass(frozen=True)
class WebExecutionRunResult:
    execution_id: str
    status: WebExecutionRunStatus


@dataclass(frozen=True)
class _PreparedExecution:
    conversation: ChatConversation
    runtime: ResolvedAgentRuntime
    history: list[dict[str, str]]
    tools: list[dict]
    tool_configs: dict[str, dict]
    context: ToolExecutionContext


class WebExecutionRunner:
    """Commit a claim, run the neutral agent loop, then atomically record it."""

    def __init__(
        self,
        *,
        worker_id: str,
        lease_duration: timedelta,
        queue_service: WebExecutionQueueService = web_execution_queue_service,
        runtime_resolver: AgentRuntimeResolver = agent_runtime_resolver,
        policy_service: ToolPolicyService = tool_policy_service,
        agent_loop: AgentLoop = run_agent_loop,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._queue = queue_service
        self._runtime_resolver = runtime_resolver
        self._policy = policy_service
        self._agent_loop = agent_loop
        self._session_factory = session_factory

    async def run_once(self) -> bool:
        claim = await self.claim_once()
        if claim is None:
            return False
        await self.execute_claim(claim)
        return True

    async def claim_once(self) -> ClaimedWebExecution | None:
        """Commit ownership before starting model or tool execution."""
        async with self._session_factory() as db:
            async with db.begin():
                return await self._queue.claim_next(
                    db,
                    worker_id=self._worker_id,
                    lease_duration=self._lease_duration,
                )

    async def execute_claim(
        self,
        claim: ClaimedWebExecution,
    ) -> WebExecutionRunResult:
        started = time.monotonic()
        try:
            owned = await self._revalidate_claim(claim)
        except WebExecutionLeaseExpiredError:
            return await self._record_terminal(
                claim,
                outcome=WebExecutionOutcome.BLOCKED,
                safe_code="stale_execution_lease",
                started=started,
            )
        except WebExecutionAutomationBlockedError:
            return await self._record_terminal(
                claim,
                outcome=WebExecutionOutcome.BLOCKED,
                safe_code="conversation_control_changed",
                started=started,
            )
        except WebExecutionClaimOwnershipError:
            return self._claim_lost_result(claim)

        async with self._session_factory() as db:
            try:
                async with db.begin():
                    prepared = await self._prepare(db, owned)
                    result = await self._run_agent(db, owned, prepared)
                    recorded = await self._record_agent_result(
                        db,
                        owned=owned,
                        result=result,
                        duration_ms=self._duration_ms(started),
                    )
                    return self._run_result(recorded)
            except (
                AutomationBlockedError,
                ControlVersionConflictError,
                WebExecutionAutomationBlockedError,
            ):
                return await self._record_terminal(
                    claim,
                    outcome=WebExecutionOutcome.BLOCKED,
                    safe_code="conversation_control_changed",
                    started=started,
                )
            except AgentRuntimeUnavailable:
                return await self._record_terminal(
                    claim,
                    outcome=WebExecutionOutcome.FAILED,
                    safe_code="agent_runtime_unavailable",
                    started=started,
                )
            except WebExecutionClaimOwnershipError:
                return self._claim_lost_result(claim)
            except Exception as exc:
                logger.error(
                    "web_execution_failed",
                    extra={
                        "execution_id": str(claim.execution.id),
                        "error_type": type(exc).__name__,
                    },
                )
                return await self._record_terminal(
                    claim,
                    outcome=WebExecutionOutcome.BLOCKED,
                    safe_code="agent_execution_uncertain",
                    started=started,
                )

    async def _revalidate_claim(
        self,
        claim: ClaimedWebExecution,
    ) -> ClaimedWebExecution:
        # The lock is intentionally committed before model I/O. Keeping the
        # execution row locked would invert reset's conversation/execution lock
        # order and could deadlock session closure.
        async with self._session_factory() as db:
            async with db.begin():
                return await self._queue.revalidate_claim(
                    db,
                    execution_id=claim.execution.id,
                    worker_id=self._worker_id,
                )

    async def _prepare(
        self,
        db: AsyncSession,
        claim: ClaimedWebExecution,
    ) -> _PreparedExecution:
        conversation = (
            (
                await db.execute(
                    select(ChatConversation).where(
                        ChatConversation.id == claim.execution.conversation_id,
                        ChatConversation.channel == "web",
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        if conversation is None or conversation.channel_route_id is None:
            raise AgentRuntimeUnavailable("web conversation route is unavailable")
        resolved = await self._runtime_resolver.resolve_route(
            db,
            "web",
            conversation.route_key,
            require_public=True,
        )
        if (
            resolved.route.id != conversation.channel_route_id
            or resolved.route.agent_id != conversation.agent_id
        ):
            raise AgentRuntimeUnavailable("web conversation route is unavailable")
        runtime = resolved.runtime
        context = ToolExecutionContext(
            request_id=claim.execution.request_id,
            channel="web",
            principal_id=str(conversation.principal_id),
            conversation_id=str(conversation.id),
            agent_id=str(conversation.agent_id),
            external_subject=conversation.external_thread_id,
            scopes=set(),
            allowed_source_ids=set(),
        )
        tools = await self._policy.available_tools(
            db,
            context,
            set(tool_registry.list_tools()),
        )
        tool_names = [item["tool_name"] for item in tools]
        tool_configs = await self._load_tool_configs(db, tool_names)
        history = await self._load_history(
            db,
            conversation_id=conversation.id,
            inbound_message_id=claim.inbound_message.id,
            limit=runtime.config.history_message_limit,
        )
        return _PreparedExecution(
            conversation=conversation,
            runtime=runtime,
            history=history,
            tools=tools,
            tool_configs=tool_configs,
            context=context,
        )

    async def _run_agent(
        self,
        db: AsyncSession,
        claim: ClaimedWebExecution,
        prepared: _PreparedExecution,
    ) -> AgentLoopResult:
        async def automation_guard() -> None:
            await conversation_control_service.assert_automation_allowed(
                db,
                conversation_id=prepared.conversation.id,
                agent_id=prepared.conversation.agent_id,
                expected_version=claim.execution.control_version,
            )

        await automation_guard()
        return await self._agent_loop(
            user_message=claim.inbound_message.content,
            conversation_history=prepared.history,
            available_tools=prepared.tools,
            tool_configs=prepared.tool_configs,
            profile=prepared.runtime.profile,
            user_id=None,
            phone=prepared.conversation.external_thread_id,
            request_id=claim.execution.request_id,
            db=db,
            conversation_summary=prepared.conversation.summary,
            rag_area_ids_override=set(),
            execution_context=prepared.context,
            runtime=prepared.runtime,
            automation_guard=automation_guard,
        )

    async def _record_agent_result(
        self,
        db: AsyncSession,
        *,
        owned: ClaimedWebExecution,
        result: AgentLoopResult,
        duration_ms: int,
    ) -> RecordedWebExecutionOutcome:
        if result.status == "success" and result.response_text.strip():
            return await self._queue.record_outcome(
                db,
                execution_id=owned.execution.id,
                worker_id=self._worker_id,
                outcome=WebExecutionOutcome.COMPLETED,
                output_content=result.response_text,
                tools_used=result.tools_used,
                duration_ms=duration_ms,
            )
        safe_code = {
            "timeout": "agent_execution_timeout",
            "max_iterations": "agent_max_iterations",
        }.get(result.status, "agent_execution_failed")
        return await self._queue.record_outcome(
            db,
            execution_id=owned.execution.id,
            worker_id=self._worker_id,
            outcome=WebExecutionOutcome.FAILED,
            safe_code=safe_code,
            duration_ms=duration_ms,
        )

    async def _record_terminal(
        self,
        claim: ClaimedWebExecution,
        *,
        outcome: WebExecutionOutcome,
        safe_code: str,
        started: float,
    ) -> WebExecutionRunResult:
        async with self._session_factory() as db:
            try:
                async with db.begin():
                    recorded = await self._queue.record_outcome(
                        db,
                        execution_id=claim.execution.id,
                        worker_id=self._worker_id,
                        outcome=outcome,
                        safe_code=safe_code,
                        duration_ms=self._duration_ms(started),
                    )
            except WebExecutionClaimOwnershipError:
                return WebExecutionRunResult(
                    execution_id=str(claim.execution.id),
                    status=WebExecutionRunStatus.CLAIM_LOST,
                )
        return self._run_result(recorded)

    @staticmethod
    async def _load_tool_configs(
        db: AsyncSession,
        tool_names: list[str],
    ) -> dict[str, dict]:
        if not tool_names:
            return {}
        rows = (
            (
                await db.execute(
                    select(ToolConfig).where(ToolConfig.tool_name.in_(tool_names))
                )
            )
            .scalars()
            .all()
        )
        return {
            row.tool_name: {
                "params_schema": row.params_schema or {},
                "timeout_seconds": row.timeout_seconds,
            }
            for row in rows
        }

    @staticmethod
    async def _load_history(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        inbound_message_id: uuid.UUID,
        limit: int,
    ) -> list[dict[str, str]]:
        if limit <= 0:
            return []
        rows = list(
            (
                (
                    await db.execute(
                        select(ChatMessage)
                        .where(
                            ChatMessage.conversation_id == conversation_id,
                            ChatMessage.id != inbound_message_id,
                            ChatMessage.status == "completed",
                            ChatMessage.role.in_(("user", "assistant")),
                        )
                        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        )
        rows.reverse()
        return [{"role": row.role, "content": row.content} for row in rows]

    @staticmethod
    def _run_result(recorded: RecordedWebExecutionOutcome) -> WebExecutionRunResult:
        status = (
            WebExecutionRunStatus(recorded.execution.status)
            if recorded.execution.status
            in {
                WebExecutionRunStatus.COMPLETED,
                WebExecutionRunStatus.FAILED,
                WebExecutionRunStatus.BLOCKED,
            }
            else WebExecutionRunStatus.CLAIM_LOST
        )
        return WebExecutionRunResult(
            execution_id=str(recorded.execution.id),
            status=status,
        )

    @staticmethod
    def _claim_lost_result(claim: ClaimedWebExecution) -> WebExecutionRunResult:
        logger.info(
            "web_execution_claim_lost",
            extra={"execution_id": str(claim.execution.id)},
        )
        return WebExecutionRunResult(
            execution_id=str(claim.execution.id),
            status=WebExecutionRunStatus.CLAIM_LOST,
        )

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))
