"""Server-side tool authorization independent of model selection."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_resource_binding import AgentSourceBinding, AgentToolBinding
from app.models.integration_source import IntegrationSource
from app.models.tool_config import ToolConfig
from app.schemas.tools import ToolExecutionContext

logger = logging.getLogger(__name__)


class ToolPolicyService:
    async def available_tools(
        self,
        db: AsyncSession,
        context: ToolExecutionContext,
        runtime_registered_tools: set[str],
    ) -> list[dict]:
        stmt = (
            select(ToolConfig, IntegrationSource)
            .outerjoin(IntegrationSource, ToolConfig.source_id == IntegrationSource.id)
            .where(ToolConfig.is_enabled == True)  # noqa: E712
        )
        if context.agent_id is not None:
            try:
                agent_id = uuid.UUID(context.agent_id)
            except ValueError:
                logger.warning("tool_policy_invalid_agent_id")
                return []
            stmt = (
                stmt.join(
                    AgentToolBinding,
                    AgentToolBinding.tool_id == ToolConfig.id,
                )
                .outerjoin(
                    AgentSourceBinding,
                    (AgentSourceBinding.source_id == ToolConfig.source_id)
                    & (AgentSourceBinding.agent_id == agent_id),
                )
                .where(
                    AgentToolBinding.agent_id == agent_id,
                    or_(
                        ToolConfig.source_id.is_(None),
                        AgentSourceBinding.id.is_not(None),
                    ),
                )
            )
        # ``agent_id=None`` is a temporary compatibility path for legacy callers.
        rows = (await db.execute(stmt)).all()
        available: list[dict] = []
        for tool, source in rows:
            if tool.tool_name not in runtime_registered_tools:
                continue
            if context.channel not in {
                str(item) for item in (tool.allowed_channels or [])
            }:
                continue
            if tool.handler_kind == "http_api":
                if source is None or not source.is_active:
                    continue
                if context.channel == "web" and not source.is_public:
                    continue
                if (
                    context.allowed_source_ids
                    and str(source.id) not in context.allowed_source_ids
                ):
                    continue
            if tool.risk_level == "write" and "tools:write" not in context.scopes:
                continue
            available.append(
                {
                    "tool_name": tool.tool_name,
                    "description": tool.description or "",
                    "source_system": source.slug
                    if source is not None
                    else tool.source_system,
                    "source_id": str(source.id) if source is not None else None,
                    "risk_level": tool.risk_level,
                }
            )
        return available

    async def is_allowed(
        self,
        db: AsyncSession,
        tool_name: str,
        context: ToolExecutionContext,
        runtime_registered_tools: set[str],
    ) -> bool:
        tools = await self.available_tools(db, context, runtime_registered_tools)
        return any(item["tool_name"] == tool_name for item in tools)


tool_policy_service = ToolPolicyService()
