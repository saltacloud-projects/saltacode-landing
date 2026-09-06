"""PostgreSQL coverage for deterministic agent handoff routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_handoff_route import (
    AgentHandoffRoute,
    AgentHandoffRouteReceipt,
)
from app.models.agent_profile import AgentProfile
from app.routers.admin.agent_handoff_routes import _require_target_manage
from app.services.admin_agent_access import admin_agent_access_service
from app.services.agent_handoff_routes import (
    AgentHandoffRouteConflictError,
    AgentHandoffRouteIdempotencyError,
    AgentHandoffRouteNotFoundError,
    AgentHandoffRouteService,
    AgentHandoffRouteValidationError,
    AgentHandoffRouteVersionConflictError,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class HandoffContext:
    source_agent_id: UUID
    target_agent_id: UUID
    alternate_target_agent_id: UUID
    inactive_agent_id: UUID
    foreign_agent_id: UUID
    admin_id: UUID
    role_key: str


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


def _agent(label: str, *, active: bool = True) -> AgentProfile:
    suffix = uuid4().hex
    return AgentProfile(
        name=f"Handoff {label}",
        slug=f"handoff-{label}-{suffix}",
        version=1,
        is_active=active,
        is_public=False,
        retention_days=30,
        description=None,
        prompt_identity="Test identity",
        prompt_domain="Test domain",
        prompt_guardrails="Test guardrails",
        unauthorized_message="Unauthorized",
        error_message="Error",
        created_by="integration-test",
    )


@pytest.fixture
async def handoff_context() -> HandoffContext:
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        role = AdminRole(
            key=f"handoff-{suffix}"[:40],
            name="Handoff test role",
            description=None,
            permissions=["runtime.read", "runtime.manage"],
            is_active=True,
            is_system=False,
        )
        admin = AdminUser(
            email=f"handoff-{suffix}@example.test",
            hashed_password="not-used",
            name="Handoff test admin",
            role=role.key,
            is_active=True,
            must_change_password=False,
        )
        source = _agent("source")
        target = _agent("target")
        alternate = _agent("alternate")
        inactive = _agent("inactive", active=False)
        foreign = _agent("foreign")
        db.add_all([role, admin, source, target, alternate, inactive, foreign])
        await db.flush()
        for agent_id in (source.id, target.id):
            await admin_agent_access_service.set_grant(
                db,
                admin_user_id=admin.id,
                role_key=admin.role,
                agent_id=agent_id,
                permissions=["runtime.read", "runtime.manage"],
                created_by="integration-test",
            )
        await db.commit()
        context = HandoffContext(
            source_agent_id=source.id,
            target_agent_id=target.id,
            alternate_target_agent_id=alternate.id,
            inactive_agent_id=inactive.id,
            foreign_agent_id=foreign.id,
            admin_id=admin.id,
            role_key=role.key,
        )

    try:
        yield context
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(AgentHandoffRoute).where(
                    AgentHandoffRoute.source_agent_id == context.source_agent_id
                )
            )
            await db.execute(
                delete(AdminAgentGrant).where(
                    AdminAgentGrant.admin_user_id == context.admin_id
                )
            )
            await db.execute(delete(AdminUser).where(AdminUser.id == context.admin_id))
            await db.execute(delete(AdminRole).where(AdminRole.key == context.role_key))
            await db.execute(
                delete(AgentProfile).where(
                    AgentProfile.id.in_(
                        [
                            context.source_agent_id,
                            context.target_agent_id,
                            context.alternate_target_agent_id,
                            context.inactive_agent_id,
                            context.foreign_agent_id,
                        ]
                    )
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_handoff_route_lifecycle_is_cas_idempotent_and_append_only(
    handoff_context: HandoffContext,
) -> None:
    context = handoff_context
    service = AgentHandoffRouteService()
    started_at = datetime.now(UTC)

    async with AsyncSessionLocal() as db:
        created = await service.create_route(
            db,
            source_agent_id=context.source_agent_id,
            target_agent_id=context.target_agent_id,
            trigger="quote_requested",
            is_active=True,
            actor_admin_id=context.admin_id,
            idempotency_key="handoff-create-1",
            occurred_at=started_at,
        )
        duplicate = await service.create_route(
            db,
            source_agent_id=context.source_agent_id,
            target_agent_id=context.target_agent_id,
            trigger="quote_requested",
            is_active=True,
            actor_admin_id=context.admin_id,
            idempotency_key="handoff-create-1",
            occurred_at=started_at + timedelta(seconds=1),
        )
        assert created.applied is True
        assert duplicate.applied is False
        assert duplicate.route.id == created.route.id
        assert created.route.control_version == 0

        with pytest.raises(AgentHandoffRouteIdempotencyError):
            await service.create_route(
                db,
                source_agent_id=context.source_agent_id,
                target_agent_id=context.alternate_target_agent_id,
                trigger="quote_requested",
                is_active=True,
                actor_admin_id=context.admin_id,
                idempotency_key="handoff-create-1",
            )
        with pytest.raises(AgentHandoffRouteConflictError):
            await service.create_route(
                db,
                source_agent_id=context.source_agent_id,
                target_agent_id=context.target_agent_id,
                trigger="quote_requested",
                is_active=True,
                actor_admin_id=context.admin_id,
                idempotency_key="handoff-create-2",
            )

        changed = await service.update_route(
            db,
            source_agent_id=context.source_agent_id,
            route_id=created.route.id,
            target_agent_id=context.alternate_target_agent_id,
            is_active=None,
            actor_admin_id=context.admin_id,
            expected_version=0,
            idempotency_key="handoff-update-1",
            occurred_at=started_at + timedelta(seconds=2),
        )
        assert changed.applied is True
        assert changed.route.target_agent_id == context.alternate_target_agent_id
        assert changed.route.control_version == 1

        repeated = await service.update_route(
            db,
            source_agent_id=context.source_agent_id,
            route_id=created.route.id,
            target_agent_id=context.alternate_target_agent_id,
            is_active=None,
            actor_admin_id=context.admin_id,
            expected_version=0,
            idempotency_key="handoff-update-1",
        )
        assert repeated.applied is False
        assert repeated.route.control_version == 1

        with pytest.raises(AgentHandoffRouteVersionConflictError):
            await service.deactivate_route(
                db,
                source_agent_id=context.source_agent_id,
                route_id=created.route.id,
                actor_admin_id=context.admin_id,
                expected_version=0,
                idempotency_key="handoff-deactivate-stale",
            )

        deactivated = await service.deactivate_route(
            db,
            source_agent_id=context.source_agent_id,
            route_id=created.route.id,
            actor_admin_id=context.admin_id,
            expected_version=1,
            idempotency_key="handoff-deactivate-1",
            occurred_at=started_at + timedelta(seconds=3),
        )
        no_op = await service.deactivate_route(
            db,
            source_agent_id=context.source_agent_id,
            route_id=created.route.id,
            actor_admin_id=context.admin_id,
            expected_version=2,
            idempotency_key="handoff-deactivate-2",
            occurred_at=started_at + timedelta(seconds=4),
        )
        await db.commit()

        assert deactivated.applied is True
        assert no_op.applied is False
        assert no_op.route.is_active is False
        assert no_op.route.control_version == 2
        receipts = list(
            (
                await db.execute(
                    select(AgentHandoffRouteReceipt)
                    .where(AgentHandoffRouteReceipt.route_id == created.route.id)
                    .order_by(AgentHandoffRouteReceipt.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [receipt.command_type for receipt in receipts] == [
            "created",
            "updated",
            "deactivated",
            "deactivated",
        ]
        assert [receipt.applied for receipt in receipts] == [True, True, True, False]
        assert len({receipt.idempotency_key for receipt in receipts}) == 4


@pytest.mark.asyncio
async def test_handoff_routes_reject_invalid_targets_and_cross_agent_reads(
    handoff_context: HandoffContext,
) -> None:
    context = handoff_context
    service = AgentHandoffRouteService()

    async with AsyncSessionLocal() as db:
        for target_id in (context.source_agent_id, context.inactive_agent_id):
            with pytest.raises(AgentHandoffRouteValidationError):
                await service.create_route(
                    db,
                    source_agent_id=context.source_agent_id,
                    target_agent_id=target_id,
                    trigger="manual_escalation",
                    is_active=True,
                    actor_admin_id=context.admin_id,
                    idempotency_key=f"invalid-{target_id}",
                )

        created = await service.create_route(
            db,
            source_agent_id=context.source_agent_id,
            target_agent_id=context.target_agent_id,
            trigger="manual_escalation",
            is_active=True,
            actor_admin_id=context.admin_id,
            idempotency_key="scoped-create",
        )
        with pytest.raises(AgentHandoffRouteNotFoundError):
            await service.get_route(
                db,
                source_agent_id=context.foreign_agent_id,
                route_id=created.route.id,
            )


@pytest.mark.asyncio
async def test_target_agent_mutations_require_runtime_manage_grant(
    handoff_context: HandoffContext,
) -> None:
    context = handoff_context

    async with AsyncSessionLocal() as db:
        admin = await db.get(AdminUser, context.admin_id)
        await _require_target_manage(
            db,
            admin=admin,
            target_agent_id=context.target_agent_id,
        )
        with pytest.raises(HTTPException) as error:
            await _require_target_manage(
                db,
                admin=admin,
                target_agent_id=context.alternate_target_agent_id,
            )
        assert error.value.status_code == 403
