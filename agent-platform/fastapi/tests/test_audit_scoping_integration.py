"""PostgreSQL integration coverage for truthful agent-scoped audit reads."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_runtime import ChannelAgentRoute
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditListFilter, AuditLogCreate
from app.schemas.common import StatusEnum
from app.services.audit import AuditService

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_scoped_list_excludes_legacy_null_rows() -> None:
    scoped_request_id = uuid4()
    legacy_request_id = uuid4()
    service = AuditService()

    try:
        async with AsyncSessionLocal() as db:
            route = (
                (
                    await db.execute(
                        select(ChannelAgentRoute).where(
                            ChannelAgentRoute.is_active.is_(True)
                        )
                    )
                )
                .scalars()
                .first()
            )
            assert route is not None, "bootstrap must provide an active channel route"
            await service.log(
                db,
                AuditLogCreate(
                    agent_id=route.agent_id,
                    channel_route_id=route.id,
                    request_id=str(scoped_request_id),
                    phone_number="549audit-scoped",
                    status=StatusEnum.success,
                ),
            )
            await service.log(
                db,
                AuditLogCreate(
                    request_id=str(legacy_request_id),
                    phone_number="549audit-legacy",
                    status=StatusEnum.success,
                ),
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            rows = await service.list_logs(
                db,
                AuditListFilter(agent_id=route.agent_id, limit=500),
            )
            request_ids = {row.request_id for row in rows}
            assert scoped_request_id in request_ids
            assert legacy_request_id not in request_ids
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(AuditLog).where(
                    AuditLog.request_id.in_([scoped_request_id, legacy_request_id])
                )
            )
            await db.commit()
