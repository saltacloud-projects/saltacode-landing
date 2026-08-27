"""Administration of source-bound declarative tools."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.integration_source import IntegrationSource
from app.models.tool_config import ToolConfig
from app.routers.admin.auth import require_permission
from app.schemas.admin import ToolConfigCreate, ToolConfigOut, ToolConfigUpdate
from app.services.admin_rbac import AdminPermission
from app.services.tools.dynamic import (
    register_one_http_api_tool,
    sync_http_api_tools,
    unregister_http_api_tool,
)
from app.services.tools.registry import tool_registry

router = APIRouter(
    tags=["admin-tools"],
    dependencies=[Depends(require_permission(AdminPermission.TOOLS_READ))],
)


@router.get("/", response_model=list[ToolConfigOut])
async def list_tools(db: AsyncSession = Depends(get_db)):
    await sync_http_api_tools(db)
    result = await db.execute(select(ToolConfig).order_by(ToolConfig.tool_name))
    tools = result.scalars().all()
    out = []
    for t in tools:
        item = ToolConfigOut.from_orm_model(t)
        # Agregar flag de si tiene adaptador registrado en runtime
        out.append(item)
    return out


@router.post(
    "/",
    response_model=ToolConfigOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(AdminPermission.TOOLS_MANAGE))],
)
async def create_tool(data: ToolConfigCreate, db: AsyncSession = Depends(get_db)):
    """Da de alta una tool tipo API (handler_kind='http_api') desde el panel."""
    existing = (
        await db.execute(
            select(ToolConfig).where(ToolConfig.tool_name == data.tool_name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"Ya existe una tool '{data.tool_name}'."
        )
    # Never shadow an audited native capability.
    if tool_registry.get(data.tool_name) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"'{data.tool_name}' está reservado por una tool del sistema.",
        )

    try:
        source_id = uuid.UUID(data.source_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="source_id inválido") from exc
    source = await db.get(IntegrationSource, source_id)
    if source is None or not source.is_active:
        raise HTTPException(
            status_code=422, detail="La fuente no existe o está deshabilitada"
        )

    tool = ToolConfig(
        tool_name=data.tool_name,
        description=data.description,
        source_system=source.slug,
        source_id=source.id,
        is_enabled=data.is_enabled,
        params_schema=data.params_schema or {},
        timeout_seconds=data.timeout_seconds,
        cost_category=data.cost_category,
        result_type=data.result_type,
        handler_kind="http_api",
        http_config=data.http_config.model_dump(),
        allowed_channels=data.allowed_channels,
        risk_level=data.risk_level,
        requires_confirmation=data.requires_confirmation,
    )
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    # Disponible de inmediato sin reiniciar (uvicorn 1 worker).
    register_one_http_api_tool(tool)
    return ToolConfigOut.from_orm_model(tool)


@router.get("/{tool_name}", response_model=ToolConfigOut)
async def get_tool(tool_name: str, db: AsyncSession = Depends(get_db)):
    tool = await _get_or_404(db, tool_name)
    return ToolConfigOut.from_orm_model(tool)


@router.patch(
    "/{tool_name}",
    response_model=ToolConfigOut,
    dependencies=[Depends(require_permission(AdminPermission.TOOLS_MANAGE))],
)
async def update_tool(
    tool_name: str, data: ToolConfigUpdate, db: AsyncSession = Depends(get_db)
):
    tool = await _get_or_404(db, tool_name)
    payload = data.model_dump(exclude_none=True)
    source_id_raw = payload.pop("source_id", None)
    if source_id_raw is not None:
        try:
            source_id = uuid.UUID(source_id_raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="source_id inválido") from exc
        source = await db.get(IntegrationSource, source_id)
        if source is None or not source.is_active:
            raise HTTPException(
                status_code=422, detail="La fuente no existe o está deshabilitada"
            )
        tool.source_id = source.id
        tool.source_system = source.slug

    # HTTP metadata is editable only for declarative operations.
    http_config = payload.pop("http_config", None)
    if http_config is not None:
        if tool.handler_kind != "http_api":
            raise HTTPException(
                status_code=400,
                detail="Solo las tools tipo API pueden editar http_config.",
            )
        tool.http_config = http_config

    source = await db.get(IntegrationSource, tool.source_id) if tool.source_id else None
    if source is None:
        raise HTTPException(
            status_code=422, detail="La tool no tiene una fuente válida"
        )
    candidate = ToolConfigCreate(
        tool_name=tool.tool_name,
        description=payload.get("description", tool.description),
        params_schema=payload.get("params_schema", tool.params_schema or {}),
        timeout_seconds=payload.get("timeout_seconds", tool.timeout_seconds),
        cost_category=payload.get("cost_category", tool.cost_category),
        result_type=payload.get("result_type", tool.result_type),
        is_enabled=payload.get("is_enabled", tool.is_enabled),
        source_id=str(source.id),
        allowed_channels=payload.get("allowed_channels", tool.allowed_channels or []),
        risk_level=payload.get("risk_level", tool.risk_level),
        requires_confirmation=payload.get(
            "requires_confirmation", tool.requires_confirmation
        ),
        http_config=tool.http_config or {},
    )

    for field, value in payload.items():
        setattr(tool, field, getattr(candidate, field))

    await db.commit()
    await db.refresh(tool)
    # Reflejar cambios (http_config/params/timeout/result_type) en runtime.
    if tool.handler_kind == "http_api":
        register_one_http_api_tool(tool)
    return ToolConfigOut.from_orm_model(tool)


@router.delete(
    "/{tool_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.TOOLS_MANAGE))],
)
async def delete_tool(tool_name: str, db: AsyncSession = Depends(get_db)):
    """Delete a panel-managed HTTP operation; audited native tools are immutable."""
    tool = await _get_or_404(db, tool_name)
    if tool.handler_kind != "http_api":
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden borrar tools tipo API creadas desde el panel.",
        )
    await db.delete(tool)
    await db.commit()
    unregister_http_api_tool(tool_name)
    return None


@router.get("/runtime/registered")
async def list_runtime_tools():
    """Lista las tools registradas en el runtime de Python (adapters cargados)."""
    return {"runtime_tools": sorted(tool_registry.list_tools())}


async def _get_or_404(db: AsyncSession, tool_name: str) -> ToolConfig:
    result = await db.execute(
        select(ToolConfig).where(ToolConfig.tool_name == tool_name)
    )
    tool = result.scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' no encontrada")
    return tool
