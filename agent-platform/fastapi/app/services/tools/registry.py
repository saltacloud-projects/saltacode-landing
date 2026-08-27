"""Runtime tool registry with channel-neutral execution context."""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from app.core.concurrency import integration_semaphore
from app.schemas.tools import ToolExecutionContext, ToolResult, coerce_execution_context

logger = logging.getLogger(__name__)


class AbstractTool(ABC):
    """Interfaz base que deben implementar todos los adapters."""

    tool_name: str

    @abstractmethod
    async def invoke(
        self,
        params: dict[str, Any],
        request_id: str,
        context: ToolExecutionContext | str | None,
    ) -> ToolResult: ...

    async def _timed_invoke(
        self,
        params: dict,
        request_id: str,
        context: ToolExecutionContext | str | None,
    ) -> ToolResult:
        execution_context = coerce_execution_context(context, request_id=request_id)
        start = time.monotonic()
        result = await self.invoke(params, request_id, execution_context)
        result.duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_invoked",
            extra={
                "tool": self.tool_name,
                "request_id": request_id,
                "channel": execution_context.channel,
                "principal_id": execution_context.principal_id,
                "duration_ms": result.duration_ms,
                "status": result.status,
            },
        )
        return result


class ToolRegistry:
    """Singleton que registra y despacha herramientas por nombre."""

    def __init__(self):
        self._tools: dict[str, AbstractTool] = {}

    def register(self, tool: AbstractTool) -> None:
        self._tools[tool.tool_name] = tool

    def get(self, tool_name: str) -> AbstractTool | None:
        return self._tools.get(tool_name)

    def unregister(self, tool_name: str) -> None:
        """Quita una tool del registry (usado al borrar tools declarativas)."""
        self._tools.pop(tool_name, None)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    async def invoke(
        self,
        tool_name: str,
        params: dict,
        request_id: str,
        context: ToolExecutionContext | str | None = None,
        phone_number: str | None = None,
    ) -> ToolResult:
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                request_id=request_id,
                tool_name=tool_name,
                status="error",
                error=f"Herramienta '{tool_name}' no encontrada",
            )
        execution_context = coerce_execution_context(
            context if context is not None else phone_number,
            request_id=request_id,
        )
        # Global safety cap. Integration-specific limits are enforced by the
        # source executor and can evolve independently.
        async with integration_semaphore:
            return await tool._timed_invoke(params, request_id, execution_context)


# Singleton global
tool_registry = ToolRegistry()
