"""Persist one explicit policy without changing historical route ownership."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_profile import AgentProfile
from app.models.audit_log import AuditLog
from app.models.commercial_progression_policy import CommercialProgressionPolicy
from app.schemas.commercial_progression import (
    CommercialProgressionOut,
    CommercialProgressionUpdate,
)


class ProgressionPolicyNotFoundError(Exception):
    pass


class ProgressionPolicyConflictError(Exception):
    pass


class CommercialProgressionService:
    async def get(
        self, db: AsyncSession, agent_id: uuid.UUID
    ) -> CommercialProgressionOut:
        policy = await db.get(CommercialProgressionPolicy, agent_id)
        return CommercialProgressionOut(
            agent_id=agent_id,
            quote_request_action=policy.quote_request_action if policy else "handoff",
            version=policy.version if policy else 0,
            is_configured=policy is not None,
        )

    async def configure(
        self,
        db: AsyncSession,
        *,
        agent_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        request: CommercialProgressionUpdate,
    ) -> CommercialProgressionOut:
        # Lock the parent as well as existing policy rows: two first writes must
        # not both pass expected_version=0 before either inserts the child.
        agent = (
            await db.execute(
                select(AgentProfile.id)
                .where(AgentProfile.id == agent_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if agent is None:
            raise ProgressionPolicyNotFoundError("agent not found")
        policy = await db.get(
            CommercialProgressionPolicy, agent_id, populate_existing=True
        )
        actual_version = policy.version if policy else 0
        if request.expected_version != actual_version:
            raise ProgressionPolicyConflictError("progression policy changed")
        previous_action = policy.quote_request_action if policy else "handoff"
        if policy is None:
            policy = CommercialProgressionPolicy(agent_id=agent_id)
            db.add(policy)
        policy.quote_request_action = request.quote_request_action
        policy.version = actual_version + 1
        policy.updated_by_admin_id = actor_admin_id
        db.add(
            AuditLog(
                agent_id=agent_id,
                request_id=uuid.uuid4(),
                phone_number="admin",
                channel="admin",
                input_type="text",
                intent="commercial.progression.configured",
                status="success",
                extra_metadata={
                    "actor_admin_id": str(actor_admin_id),
                    "previous_action": previous_action,
                    "quote_request_action": policy.quote_request_action,
                    "version": policy.version,
                },
            )
        )
        await db.flush()
        return await self.get(db, agent_id)


commercial_progression_service = CommercialProgressionService()
