"""Application queries and commands for explicit agent resource ownership."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.agent_resource_binding import (
    AgentKnowledgeBlockBinding,
    AgentOrganizationAreaBinding,
    AgentSourceBinding,
    AgentToolBinding,
)
from app.models.integration_source import IntegrationSource
from app.models.knowledge_block import KnowledgeBlock
from app.models.rag import Document, DocumentFolder, OrganizationArea
from app.models.tool_config import ToolConfig


class AgentResourceService:
    async def get_agent(
        self, db: AsyncSession, agent_id: uuid.UUID
    ) -> AgentProfile | None:
        return await db.get(AgentProfile, agent_id)

    async def list_sources(
        self, db: AsyncSession, agent_id: uuid.UUID
    ) -> list[IntegrationSource]:
        return list(
            (
                await db.execute(
                    select(IntegrationSource)
                    .join(
                        AgentSourceBinding,
                        AgentSourceBinding.source_id == IntegrationSource.id,
                    )
                    .where(AgentSourceBinding.agent_id == agent_id)
                    .order_by(IntegrationSource.name, IntegrationSource.slug)
                )
            )
            .scalars()
            .all()
        )

    async def list_tools(
        self, db: AsyncSession, agent_id: uuid.UUID
    ) -> list[ToolConfig]:
        return list(
            (
                await db.execute(
                    select(ToolConfig)
                    .join(
                        AgentToolBinding,
                        AgentToolBinding.tool_id == ToolConfig.id,
                    )
                    .where(AgentToolBinding.agent_id == agent_id)
                    .order_by(ToolConfig.tool_name)
                )
            )
            .scalars()
            .all()
        )

    async def list_knowledge_blocks(
        self,
        db: AsyncSession,
        agent_id: uuid.UUID,
        *,
        enabled_only: bool = False,
    ) -> list[KnowledgeBlock]:
        stmt = (
            select(KnowledgeBlock)
            .join(
                AgentKnowledgeBlockBinding,
                AgentKnowledgeBlockBinding.knowledge_block_id == KnowledgeBlock.id,
            )
            .where(AgentKnowledgeBlockBinding.agent_id == agent_id)
        )
        if enabled_only:
            stmt = stmt.where(KnowledgeBlock.is_enabled == True)  # noqa: E712
        stmt = stmt.order_by(KnowledgeBlock.sort_order, KnowledgeBlock.key)
        return list((await db.execute(stmt)).scalars().all())

    async def list_document_areas(
        self, db: AsyncSession, agent_id: uuid.UUID
    ) -> list[tuple[OrganizationArea, int, int]]:
        folder_counts = (
            select(
                DocumentFolder.area_id.label("area_id"),
                func.count(DocumentFolder.id).label("folder_count"),
            )
            .group_by(DocumentFolder.area_id)
            .subquery()
        )
        document_counts = (
            select(
                DocumentFolder.area_id.label("area_id"),
                func.count(Document.id).label("document_count"),
            )
            .join(Document, Document.folder_id == DocumentFolder.id)
            .where(Document.deleted_at.is_(None))
            .group_by(DocumentFolder.area_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(
                    OrganizationArea,
                    func.coalesce(folder_counts.c.folder_count, 0),
                    func.coalesce(document_counts.c.document_count, 0),
                )
                .join(
                    AgentOrganizationAreaBinding,
                    AgentOrganizationAreaBinding.area_id == OrganizationArea.id,
                )
                .outerjoin(
                    folder_counts, folder_counts.c.area_id == OrganizationArea.id
                )
                .outerjoin(
                    document_counts,
                    document_counts.c.area_id == OrganizationArea.id,
                )
                .where(AgentOrganizationAreaBinding.agent_id == agent_id)
                .order_by(OrganizationArea.name)
            )
        ).all()
        return [
            (area, int(folder_count), int(document_count))
            for area, folder_count, document_count in rows
        ]

    async def assigned_area_ids(
        self, db: AsyncSession, agent_id: uuid.UUID
    ) -> set[uuid.UUID]:
        return set(
            (
                await db.execute(
                    select(AgentOrganizationAreaBinding.area_id).where(
                        AgentOrganizationAreaBinding.agent_id == agent_id
                    )
                )
            )
            .scalars()
            .all()
        )

    async def assign_source(
        self, db: AsyncSession, agent_id: uuid.UUID, source_id: uuid.UUID
    ) -> None:
        await self._assign(
            db,
            AgentSourceBinding,
            AgentSourceBinding.source_id,
            agent_id,
            source_id,
        )

    async def assign_tool(
        self, db: AsyncSession, agent_id: uuid.UUID, tool_id: uuid.UUID
    ) -> None:
        await self._assign(
            db,
            AgentToolBinding,
            AgentToolBinding.tool_id,
            agent_id,
            tool_id,
        )

    async def assign_knowledge_block(
        self, db: AsyncSession, agent_id: uuid.UUID, block_id: uuid.UUID
    ) -> None:
        await self._assign(
            db,
            AgentKnowledgeBlockBinding,
            AgentKnowledgeBlockBinding.knowledge_block_id,
            agent_id,
            block_id,
        )

    async def assign_document_area(
        self, db: AsyncSession, agent_id: uuid.UUID, area_id: uuid.UUID
    ) -> None:
        await self._assign(
            db,
            AgentOrganizationAreaBinding,
            AgentOrganizationAreaBinding.area_id,
            agent_id,
            area_id,
        )

    async def unassign_source(
        self, db: AsyncSession, agent_id: uuid.UUID, source_id: uuid.UUID
    ) -> None:
        await self._unassign(
            db, AgentSourceBinding, AgentSourceBinding.source_id, agent_id, source_id
        )

    async def unassign_tool(
        self, db: AsyncSession, agent_id: uuid.UUID, tool_id: uuid.UUID
    ) -> None:
        await self._unassign(
            db, AgentToolBinding, AgentToolBinding.tool_id, agent_id, tool_id
        )

    async def unassign_knowledge_block(
        self, db: AsyncSession, agent_id: uuid.UUID, block_id: uuid.UUID
    ) -> None:
        await self._unassign(
            db,
            AgentKnowledgeBlockBinding,
            AgentKnowledgeBlockBinding.knowledge_block_id,
            agent_id,
            block_id,
        )

    async def unassign_document_area(
        self, db: AsyncSession, agent_id: uuid.UUID, area_id: uuid.UUID
    ) -> None:
        await self._unassign(
            db,
            AgentOrganizationAreaBinding,
            AgentOrganizationAreaBinding.area_id,
            agent_id,
            area_id,
        )

    @staticmethod
    async def _assign(
        db: AsyncSession,
        binding_model: Any,
        resource_column: Any,
        agent_id: uuid.UUID,
        resource_id: uuid.UUID,
    ) -> None:
        resource_key = resource_column.key
        await db.execute(
            pg_insert(binding_model)
            .values(agent_id=agent_id, **{resource_key: resource_id})
            .on_conflict_do_nothing(
                index_elements=["agent_id", resource_key],
            )
        )

    @staticmethod
    async def _unassign(
        db: AsyncSession,
        binding_model: Any,
        resource_column: Any,
        agent_id: uuid.UUID,
        resource_id: uuid.UUID,
    ) -> None:
        await db.execute(
            delete(binding_model).where(
                binding_model.agent_id == agent_id,
                resource_column == resource_id,
            )
        )


agent_resource_service = AgentResourceService()
