"""Agent ownership regressions for audit persistence and admin reads."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import ForeignKeyConstraint

from app.models.audit_log import AuditLog
from app.routers.admin.audit import list_audit_logs
from app.routers.admin.audit import router as audit_router
from app.schemas.audit import AuditListFilter, AuditLogCreate
from app.schemas.common import StatusEnum
from app.services.audit import AuditService
from app.services.pipeline import PipelineService


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, rows=None, scalars=None):
        self._rows = rows or []
        self._scalars = scalars or []

    def all(self):
        return self._rows

    def scalars(self):
        return _Scalars(self._scalars)


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.flushed = False
        self.committed = False

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)

    async def commit(self):
        self.committed = True


def _assert_scope_filter(statement, agent_id: UUID) -> None:
    assert "audit_logs.agent_id" in str(statement).lower()
    assert agent_id in statement.compile().params.values()


def _audit_row(agent_id: UUID, channel_route_id: UUID):
    return SimpleNamespace(
        id=uuid4(),
        agent_id=agent_id,
        channel_route_id=channel_route_id,
        request_id=uuid4(),
        phone_number="5493875000000",
        channel="whatsapp",
        input_type="text",
        intent="agent",
        source_system="dynamic",
        tool_used=None,
        duration_ms=25,
        status="success",
        error_code=None,
        error_message=None,
        response_preview="ok",
        user_message="hello",
        tool_calls=[],
        created_at=datetime.now(timezone.utc),
    )


def test_audit_model_has_nullable_scope_foreign_keys() -> None:
    table = AuditLog.__table__
    assert table.c.agent_id.nullable is True
    assert table.c.channel_route_id.nullable is True
    assert {index.name for index in table.indexes}.issuperset(
        {"ix_audit_logs_agent_id", "ix_audit_logs_channel_route_id"}
    )
    foreign_keys = {
        tuple(constraint.column_keys): constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert foreign_keys[("agent_id",)].referred_table.name == "agent_profiles"
    assert foreign_keys[("agent_id",)].ondelete == "SET NULL"
    assert (
        foreign_keys[("channel_route_id",)].referred_table.name
        == "channel_agent_routes"
    )
    assert foreign_keys[("channel_route_id",)].ondelete == "SET NULL"


def test_audit_migration_preserves_legacy_rows_without_backfill() -> None:
    path = (
        Path(__file__).parents[1]
        / "migrations_platform/versions/e3a4b5c6d7e8_scope_audit_logs_by_agent.py"
    )
    source = path.read_text()
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    assert 'sa.Column("agent_id", sa.UUID(), nullable=True)' in upgrade
    assert 'sa.Column("channel_route_id", sa.UUID(), nullable=True)' in upgrade
    assert "UPDATE AUDIT_LOGS" not in upgrade.upper()
    assert "INSERT INTO AUDIT_LOGS" not in upgrade.upper()


@pytest.mark.asyncio
async def test_audit_service_persists_resolved_scope_and_allows_legacy_nulls() -> None:
    agent_id, route_id = uuid4(), uuid4()
    scoped_db = _Db()
    legacy_db = _Db()
    service = AuditService()

    scoped = await service.log(
        scoped_db,
        AuditLogCreate(
            agent_id=agent_id,
            channel_route_id=route_id,
            request_id=str(uuid4()),
            phone_number="5493875000000",
            status=StatusEnum.success,
        ),
    )
    legacy = await service.log(
        legacy_db,
        AuditLogCreate(
            request_id=str(uuid4()),
            phone_number="5493875000001",
            status=StatusEnum.success,
        ),
    )

    assert scoped.agent_id == agent_id
    assert scoped.channel_route_id == route_id
    assert legacy.agent_id is None
    assert legacy.channel_route_id is None
    assert scoped_db.flushed is True
    assert legacy_db.flushed is True


@pytest.mark.asyncio
async def test_audit_service_list_filters_agent_and_route() -> None:
    agent_id, route_id = uuid4(), uuid4()
    db = _Db(_Result(scalars=[]))

    await AuditService().list_logs(
        db,
        AuditListFilter(agent_id=agent_id, channel_route_id=route_id),
    )

    statement = db.statements[0]
    params = set(statement.compile().params.values())
    assert agent_id in params
    assert route_id in params


def test_admin_audit_contract_requires_agent_id() -> None:
    app = FastAPI()
    app.include_router(audit_router, prefix="/api/admin/audit")
    operation = app.openapi()["paths"]["/api/admin/audit/"]["get"]
    agent_param = next(
        item
        for item in operation["parameters"]
        if item["name"] == "agent_id" and item["in"] == "query"
    )
    assert agent_param["required"] is True


@pytest.mark.asyncio
async def test_admin_audit_query_excludes_legacy_and_other_agent_rows() -> None:
    agent_id, route_id = uuid4(), uuid4()
    row = _audit_row(agent_id, route_id)
    db = _Db(_Result(rows=[(row, "User")]))

    result = await list_audit_logs(agent_id=agent_id, limit=50, offset=0, db=db)

    _assert_scope_filter(db.statements[0], agent_id)
    assert result[0].agent_id == str(agent_id)
    assert result[0].channel_route_id == str(route_id)


@pytest.mark.asyncio
async def test_pipeline_finalize_forwards_resolved_agent_and_route_scope(
    monkeypatch,
) -> None:
    agent_id, route_id = uuid4(), uuid4()
    service = PipelineService()
    log_audit = AsyncMock()
    monkeypatch.setattr(service, "_log_audit", log_audit)
    db = _Db()
    runtime = SimpleNamespace(profile=SimpleNamespace(id=agent_id))

    await service._finalize_pipeline(
        db=db,
        redis=None,
        phone="5493875000000",
        content="hello",
        response_text="ok",
        request_id=str(uuid4()),
        input_type="text",
        start=0.0,
        intent="agent",
        source_system="dynamic",
        tool_used=None,
        status="success",
        persist_conversation=False,
        resolved_runtime=runtime,
        route_key="route-a",
        channel_route_id=route_id,
    )

    assert log_audit.await_args.kwargs["agent_id"] == agent_id
    assert log_audit.await_args.kwargs["channel_route_id"] == route_id
    assert db.committed is True
