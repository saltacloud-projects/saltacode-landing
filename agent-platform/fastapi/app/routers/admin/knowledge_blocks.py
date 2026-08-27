"""
Agent Platform — Router: Admin Knowledge Blocks
/api/admin/knowledge-blocks/* — CRUD de bloques de conocimiento editables.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.knowledge_block import KnowledgeBlock
from app.routers.admin.auth import require_admin_role, require_permission
from app.schemas.admin import (
    KnowledgeBlockCreate,
    KnowledgeBlockOut,
    KnowledgeBlockUpdate,
)
from app.services.admin_rbac import AdminPermission

router = APIRouter(
    tags=["admin-knowledge"],
    dependencies=[Depends(require_permission(AdminPermission.KNOWLEDGE_READ))],
)


@router.get("/", response_model=list[KnowledgeBlockOut])
async def list_blocks(db: AsyncSession = Depends(get_db)):
    stmt = select(KnowledgeBlock).order_by(
        KnowledgeBlock.sort_order, KnowledgeBlock.key
    )
    result = await db.execute(stmt)
    return [KnowledgeBlockOut.from_orm_model(b) for b in result.scalars().all()]


@router.get("/{key}", response_model=KnowledgeBlockOut)
async def get_block(key: str, db: AsyncSession = Depends(get_db)):
    block = await _get_or_404(db, key)
    return KnowledgeBlockOut.from_orm_model(block)


@router.post(
    "/",
    response_model=KnowledgeBlockOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin_role)],
)
async def create_block(data: KnowledgeBlockCreate, db: AsyncSession = Depends(get_db)):
    existing = (
        await db.execute(select(KnowledgeBlock).where(KnowledgeBlock.key == data.key))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Ya existe un bloque con key '{data.key}'"
        )
    block = KnowledgeBlock(**data.model_dump())
    db.add(block)
    await db.flush()
    await db.refresh(block)
    return KnowledgeBlockOut.from_orm_model(block)


@router.patch(
    "/{key}",
    response_model=KnowledgeBlockOut,
    dependencies=[Depends(require_admin_role)],
)
async def update_block(
    key: str, data: KnowledgeBlockUpdate, db: AsyncSession = Depends(get_db)
):
    block = await _get_or_404(db, key)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(block, field, value)
    await db.flush()
    await db.refresh(block)
    return KnowledgeBlockOut.from_orm_model(block)


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_role)],
)
async def delete_block(key: str, db: AsyncSession = Depends(get_db)):
    block = await _get_or_404(db, key)
    await db.delete(block)


async def _get_or_404(db: AsyncSession, key: str) -> KnowledgeBlock:
    result = await db.execute(select(KnowledgeBlock).where(KnowledgeBlock.key == key))
    block = result.scalar_one_or_none()
    if not block:
        raise HTTPException(status_code=404, detail=f"Bloque '{key}' no encontrado")
    return block
