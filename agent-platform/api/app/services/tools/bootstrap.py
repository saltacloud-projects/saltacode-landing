"""Compose the same process-local capabilities for API and durable workers."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.tools import dynamic
from app.services.tools.adapters.commercial_quote_contact_request import (
    register_commercial_quote_contact_request_tool,
)
from app.services.tools.adapters.rag import register_rag_tools
from app.services.tools.registry import tool_registry


def register_native_tools() -> None:
    """Register handlers, never grant a capability or assign it to an agent."""
    register_commercial_quote_contact_request_tool(tool_registry)
    register_rag_tools(tool_registry)


async def sync_runtime_tools(db: AsyncSession) -> int:
    """Refresh local handlers before taking a policy-filtered tool snapshot."""
    register_native_tools()
    # API administration changes a different process. Resolve current HTTP
    # declarations per execution; credentials remain invocation-time only.
    return await dynamic.sync_http_api_tools(db)
