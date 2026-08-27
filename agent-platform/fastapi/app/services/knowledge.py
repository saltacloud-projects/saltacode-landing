"""
KnowledgeService

Carga TODOS los knowledge_blocks habilitados de la DB y los concatena
al system prompt, en orden de sort_order. El código no conoce las keys
específicas — cualquier bloque que se cree desde el panel y se habilite
se inyecta automáticamente sin tocar código.

Placeholders soportados en el contenido de los bloques:
  {fecha_actual}, {ayer}, {mes_actual}, {mes_anterior}, {inicio_semana}, {abril_ejemplo}
Se resuelven automáticamente en cada request.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_block import KnowledgeBlock

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")


@dataclass(frozen=True)
class ResolvedKnowledgeBlock:
    """Prompt-ready knowledge with its persisted semantic identity preserved."""

    key: str
    title: str
    content: str
    sort_order: int


def _resolve_placeholders(template: str, ctx: dict[str, str]) -> str:
    """Reemplaza los placeholders {clave} conocidos por su valor."""
    out = template
    for key, value in ctx.items():
        out = out.replace("{" + key + "}", value)
    return out


def _unresolved_placeholders(text: str) -> list[str]:
    """Lista los placeholders {snake_case} que quedaron sin resolver."""
    return _PLACEHOLDER_RE.findall(text)


class KnowledgeService:
    async def get_blocks(
        self,
        db: AsyncSession,
        enabled_only: bool = True,
    ) -> list[KnowledgeBlock]:
        """Lista los bloques de conocimiento (ordenados por sort_order)."""
        stmt = select(KnowledgeBlock)
        if enabled_only:
            stmt = stmt.where(KnowledgeBlock.is_enabled == True)  # noqa: E712
        stmt = stmt.order_by(KnowledgeBlock.sort_order, KnowledgeBlock.key)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def build_resolved_knowledge(
        self,
        db: AsyncSession,
        ctx: dict[str, str],
    ) -> list[ResolvedKnowledgeBlock]:
        """
        Carga TODOS los bloques habilitados y conserva identidad y orden.

        El código NO conoce las keys de los bloques. Cualquier bloque nuevo
        creado desde el panel se inyecta automáticamente.
        """
        blocks = await self.get_blocks(db, enabled_only=True)
        if not blocks:
            logger.warning("knowledge_no_blocks_enabled")
            return []

        resolved: list[ResolvedKnowledgeBlock] = []
        for block in blocks:
            content = _resolve_placeholders(block.content, ctx)
            leftover = _unresolved_placeholders(content)
            if leftover:
                logger.warning(
                    "knowledge_block_unresolved_placeholders",
                    extra={
                        "key": block.key,
                        "placeholders": sorted(set(leftover))[:10],
                    },
                )
            resolved.append(
                ResolvedKnowledgeBlock(
                    key=block.key,
                    title=block.title,
                    content=content,
                    sort_order=block.sort_order,
                )
            )

        logger.info(
            "knowledge_blocks_loaded",
            extra={
                "count": len(blocks),
                "keys": [b.key for b in blocks],
                "total_chars": sum(len(block.content) for block in resolved),
            },
        )
        return resolved

    @staticmethod
    def compose_resolved_knowledge(blocks: list[ResolvedKnowledgeBlock]) -> str:
        """Compose resolved blocks exactly as the runtime prompt expects."""
        return "\n\n".join(block.content for block in blocks)

    async def build_all_knowledge(self, db: AsyncSession, ctx: dict[str, str]) -> str:
        """Resolve and concatenate every enabled block for the runtime prompt."""
        blocks = await self.build_resolved_knowledge(db, ctx)
        return self.compose_resolved_knowledge(blocks)


knowledge_service = KnowledgeService()
