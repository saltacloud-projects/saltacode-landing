"""Agent-scoped assignment API over the global platform resource libraries."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.integration_source import IntegrationSource
from app.models.knowledge_block import KnowledgeBlock
from app.models.rag import OrganizationArea
from app.models.tool_config import ToolConfig
from app.routers.admin.auth import require_admin_role, require_permission
from app.schemas.admin import KnowledgeBlockOut, ToolConfigOut
from app.schemas.integrations import IntegrationSourceOut
from app.schemas.rag import AreaOut
from app.services.admin_rbac import AdminPermission
from app.services.agent_resources import agent_resource_service

router = APIRouter(
    tags=["admin-agent-resources"],
    dependencies=[Depends(require_permission(AdminPermission.PROFILES_READ))],
)


def _uuid_or_404(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"{label} not found") from exc


async def _agent_or_404(db: AsyncSession, agent_id: str) -> uuid.UUID:
    parsed = _uuid_or_404(agent_id, "Agent")
    if await agent_resource_service.get_agent(db, parsed) is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return parsed


async def _resource_or_404(
    db: AsyncSession, model: Any, resource_id: str, label: str
) -> uuid.UUID:
    parsed = _uuid_or_404(resource_id, label)
    if await db.get(model, parsed) is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return parsed


@router.get(
    "/{agent_id}/sources",
    response_model=list[IntegrationSourceOut],
    dependencies=[Depends(require_permission(AdminPermission.SOURCES_READ))],
)
async def list_agent_sources(agent_id: str, db: AsyncSession = Depends(get_db)):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    return [
        IntegrationSourceOut.from_model(source)
        for source in await agent_resource_service.list_sources(db, parsed_agent_id)
    ]


@router.put(
    "/{agent_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.SOURCES_MANAGE))],
)
async def assign_agent_source(
    agent_id: str, source_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_source_id = await _resource_or_404(
        db, IntegrationSource, source_id, "Integration source"
    )
    await agent_resource_service.assign_source(db, parsed_agent_id, parsed_source_id)
    return None


@router.delete(
    "/{agent_id}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.SOURCES_MANAGE))],
)
async def unassign_agent_source(
    agent_id: str, source_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_source_id = await _resource_or_404(
        db, IntegrationSource, source_id, "Integration source"
    )
    await agent_resource_service.unassign_source(db, parsed_agent_id, parsed_source_id)
    return None


@router.get(
    "/{agent_id}/tools",
    response_model=list[ToolConfigOut],
    dependencies=[Depends(require_permission(AdminPermission.TOOLS_READ))],
)
async def list_agent_tools(agent_id: str, db: AsyncSession = Depends(get_db)):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    return [
        ToolConfigOut.from_orm_model(tool)
        for tool in await agent_resource_service.list_tools(db, parsed_agent_id)
    ]


@router.put(
    "/{agent_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.TOOLS_MANAGE))],
)
async def assign_agent_tool(
    agent_id: str, tool_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_tool_id = await _resource_or_404(db, ToolConfig, tool_id, "Tool")
    await agent_resource_service.assign_tool(db, parsed_agent_id, parsed_tool_id)
    return None


@router.delete(
    "/{agent_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.TOOLS_MANAGE))],
)
async def unassign_agent_tool(
    agent_id: str, tool_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_tool_id = await _resource_or_404(db, ToolConfig, tool_id, "Tool")
    await agent_resource_service.unassign_tool(db, parsed_agent_id, parsed_tool_id)
    return None


@router.get(
    "/{agent_id}/knowledge-blocks",
    response_model=list[KnowledgeBlockOut],
    dependencies=[Depends(require_permission(AdminPermission.KNOWLEDGE_READ))],
)
async def list_agent_knowledge_blocks(
    agent_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    return [
        KnowledgeBlockOut.from_orm_model(block)
        for block in await agent_resource_service.list_knowledge_blocks(
            db, parsed_agent_id
        )
    ]


@router.put(
    "/{agent_id}/knowledge-blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_role)],
)
async def assign_agent_knowledge_block(
    agent_id: str, block_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_block_id = await _resource_or_404(
        db, KnowledgeBlock, block_id, "Knowledge block"
    )
    await agent_resource_service.assign_knowledge_block(
        db, parsed_agent_id, parsed_block_id
    )
    return None


@router.delete(
    "/{agent_id}/knowledge-blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_role)],
)
async def unassign_agent_knowledge_block(
    agent_id: str, block_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_block_id = await _resource_or_404(
        db, KnowledgeBlock, block_id, "Knowledge block"
    )
    await agent_resource_service.unassign_knowledge_block(
        db, parsed_agent_id, parsed_block_id
    )
    return None


@router.get(
    "/{agent_id}/document-areas",
    response_model=list[AreaOut],
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_READ))],
)
async def list_agent_document_areas(agent_id: str, db: AsyncSession = Depends(get_db)):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    return [
        AreaOut(
            id=str(area.id),
            name=area.name,
            slug=area.slug,
            description=area.description,
            is_general=area.is_general,
            is_active=area.is_active,
            folder_count=folder_count,
            document_count=document_count,
        )
        for area, folder_count, document_count in (
            await agent_resource_service.list_document_areas(db, parsed_agent_id)
        )
    ]


@router.put(
    "/{agent_id}/document-areas/{area_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def assign_agent_document_area(
    agent_id: str, area_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_area_id = await _resource_or_404(
        db, OrganizationArea, area_id, "Document area"
    )
    await agent_resource_service.assign_document_area(
        db, parsed_agent_id, parsed_area_id
    )
    return None


@router.delete(
    "/{agent_id}/document-areas/{area_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(AdminPermission.DOCUMENTS_TAXONOMY))],
)
async def unassign_agent_document_area(
    agent_id: str, area_id: str, db: AsyncSession = Depends(get_db)
):
    parsed_agent_id = await _agent_or_404(db, agent_id)
    parsed_area_id = await _resource_or_404(
        db, OrganizationArea, area_id, "Document area"
    )
    await agent_resource_service.unassign_document_area(
        db, parsed_agent_id, parsed_area_id
    )
    return None
