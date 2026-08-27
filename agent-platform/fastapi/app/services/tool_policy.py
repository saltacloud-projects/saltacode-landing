"""Server-side tool authorization independent of model selection."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_source import IntegrationSource
from app.models.tool_config import ToolConfig
from app.schemas.tools import ToolExecutionContext


class ToolPolicyService:
    async def available_tools(
        self,
        db: AsyncSession,
        context: ToolExecutionContext,
        runtime_registered_tools: set[str],
    ) -> list[dict]:
        rows = (
            await db.execute(
                select(ToolConfig, IntegrationSource)
                .outerjoin(
                    IntegrationSource, ToolConfig.source_id == IntegrationSource.id
                )
                .where(ToolConfig.is_enabled == True)  # noqa: E712
            )
        ).all()
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
