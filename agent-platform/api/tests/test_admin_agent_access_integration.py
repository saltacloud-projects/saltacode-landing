"""PostgreSQL isolation coverage for administrator-to-agent grants."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal, engine
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.routers.admin.auth import require_agent_permission
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    yield
    await engine.dispose()


def _profile(label: str) -> AgentProfile:
    return AgentProfile(
        name=f"Grant test {label}",
        slug=f"grant-test-{label}-{uuid4().hex}",
        version=1,
        is_active=True,
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


@pytest.mark.asyncio
async def test_grants_filter_profiles_and_deny_cross_agent_access():
    admin_id = None
    agent_ids = []
    try:
        async with AsyncSessionLocal() as db:
            admin = AdminUser(
                email=f"grant-{uuid4().hex}@example.test",
                hashed_password="not-used",
                name="Grant integration admin",
                role="admin",
                is_active=True,
                must_change_password=False,
            )
            visible_agent = _profile("visible")
            foreign_agent = _profile("foreign")
            db.add_all([admin, visible_agent, foreign_agent])
            await db.flush()
            await admin_agent_access_service.set_grant(
                db,
                admin_user_id=admin.id,
                role_key=admin.role,
                agent_id=visible_agent.id,
                permissions=["*"],
                created_by="integration-test",
            )
            await db.commit()
            admin_id = admin.id
            agent_ids = [visible_agent.id, foreign_agent.id]

        async with AsyncSessionLocal() as db:
            profiles = await admin_agent_access_service.list_accessible_profiles(
                db,
                admin_user_id=admin_id,
            )
            assert [profile.id for profile in profiles] == [agent_ids[0]]

            dependency = require_agent_permission(AdminPermission.PROFILES_READ)
            admin = await db.get(AdminUser, admin_id)
            assert await dependency(str(agent_ids[0]), admin, db) is admin
            with pytest.raises(HTTPException) as error:
                await dependency(str(agent_ids[1]), admin, db)
            assert error.value.status_code == 403

            assert await admin_agent_access_service.revoke_grant(
                db,
                admin_user_id=admin_id,
                agent_id=agent_ids[0],
                updated_by=str(admin_id),
            )
            with pytest.raises(HTTPException) as revoked_error:
                await dependency(str(agent_ids[0]), admin, db)
            assert revoked_error.value.status_code == 403
    finally:
        if admin_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(AdminUser).where(AdminUser.id == admin_id))
                await db.execute(
                    delete(AgentProfile).where(AgentProfile.id.in_(agent_ids))
                )
                await db.commit()
