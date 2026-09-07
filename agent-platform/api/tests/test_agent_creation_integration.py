"""Real PostgreSQL agent creation preserves independent identities and grants."""

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.routers.admin.profiles import activate_profile, create_profile
from app.schemas.admin import ProfileCreate
from app.services.admin_agent_access import admin_agent_access_service

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_postgres_creates_independent_agents_and_grants_only_the_creator():
    async with AsyncSessionLocal() as db:
        transaction = await db.begin()
        try:
            token = uuid4().hex
            creator = AdminUser(
                email=f"agent-creator-{token}@example.test",
                hashed_password="not-a-login-credential",
                name="Creator",
                role="admin",
            )
            other = AdminUser(
                email=f"other-operator-{token}@example.test",
                hashed_password="not-a-login-credential",
                name="Other operator",
                role="admin",
            )
            db.add_all([creator, other])
            await db.flush()
            request = ProfileCreate(
                name="Independent advisor",
                slug=f"advisor-{token}",
                prompt_identity="Advisor identity",
                prompt_domain="Documented services",
                prompt_guardrails="Never invent evidence",
            )
            first = await create_profile(request, creator, db)
            second = await create_profile(
                request.model_copy(update={"slug": f"specialist-{token}"}),
                creator,
                db,
            )
            assert first.is_active is second.is_active is False
            assert first.is_public is second.is_public is False
            assert first.id != second.id
            grants = (
                (
                    await db.execute(
                        select(AdminAgentGrant).where(
                            AdminAgentGrant.agent_id.in_(
                                [UUID(first.id), UUID(second.id)]
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(grants) == 2
            assert all(grant.admin_user_id == creator.id for grant in grants)
            assert all(grant.permissions == ["*"] for grant in grants)
            assert (
                await admin_agent_access_service.list_accessible_profiles(
                    db, admin_user_id=other.id
                )
                == []
            )
            await activate_profile(first.id, db)
            await activate_profile(second.id, db)
            assert (await db.get(AgentProfile, UUID(first.id))).is_active is True
            assert (await db.get(AgentProfile, UUID(second.id))).is_active is True
            with pytest.raises(HTTPException) as conflict:
                await create_profile(request, creator, db)
            assert conflict.value.status_code == 409
        finally:
            await transaction.rollback()
