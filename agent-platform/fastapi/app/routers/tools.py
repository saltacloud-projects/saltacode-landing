"""
Agent Platform — Router: Tools
/internal/tools/* — catálogo y ejecución de herramientas
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_api_key
from app.dependencies import get_db
from app.schemas.tools import ToolExecutionContext, ToolInvokeRequest, ToolResult
from app.services.tool_policy import tool_policy_service
from app.services.tools.registry import tool_registry

router = APIRouter(tags=["tools"], dependencies=[Depends(require_api_key)])


@router.get("/")
async def list_tools():
    """Listar todas las herramientas registradas."""
    return {"tools": tool_registry.list_tools()}


@router.post("/{tool_name}/invoke", response_model=ToolResult)
async def invoke_tool(
    tool_name: str, req: ToolInvokeRequest, db: AsyncSession = Depends(get_db)
):
    """
    Invocar una herramienta por nombre.
    El registry despacha al handler real.
    """
    tool = tool_registry.get(tool_name)
    if not tool:
        raise HTTPException(
            status_code=404, detail=f"Herramienta '{tool_name}' no encontrada"
        )

    context = ToolExecutionContext(
        request_id=req.request_id,
        channel=req.channel,
        principal_id=req.principal_id,
        conversation_id=req.conversation_id,
        external_subject=req.external_subject,
        scopes=set(req.scopes),
        allowed_source_ids=set(req.allowed_source_ids),
        confirmed=req.confirmed,
    )
    if not await tool_policy_service.is_allowed(
        db, tool_name, context, set(tool_registry.list_tools())
    ):
        raise HTTPException(
            status_code=403, detail="Tool is not allowed for this execution context"
        )

    result = await tool_registry.invoke(
        tool_name=tool_name,
        params=req.params,
        request_id=req.request_id,
        context=context,
    )
    return result
