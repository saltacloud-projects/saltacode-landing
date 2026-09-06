"""Agent-scoped WhatsApp authorization and document access contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.governance import AccessCheckRequest
from app.services.agent_resources import AgentResourceService
from app.services.governance import GovernanceService
from app.services.rag.access import get_user_area_ids


class _ScalarResult:
    def __init__(self, value=None, values=None):
        self.value = value
        self.values = list(values or [])

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return self.values


class _SequenceDb:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_scoped_governance_uses_binding_policy_without_global_fallback():
    agent_id = uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        name="Shared identity",
        is_active=False,
        has_all_area_access=True,
    )
    binding = SimpleNamespace(is_active=True, has_all_area_access=False)
    service = GovernanceService()
    service._get_agent_user = AsyncMock(return_value=(user, binding))
    service._get_user = AsyncMock(side_effect=AssertionError("global fallback used"))

    response = await service.check_access(
        object(),
        AccessCheckRequest(
            request_id="scoped-access",
            phone_number="redacted",
            agent_id=agent_id,
        ),
    )

    assert response.allowed is True
    assert response.user["user_id"] == str(user.id)
    assert response.user["has_all_area_access"] is False
    service._get_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoped_governance_denies_user_not_bound_to_agent():
    service = GovernanceService()
    service._get_agent_user = AsyncMock(return_value=None)
    service._get_user = AsyncMock(side_effect=AssertionError("global fallback used"))

    response = await service.check_access(
        object(),
        AccessCheckRequest(
            request_id="wrong-agent",
            phone_number="redacted",
            agent_id=uuid4(),
        ),
    )

    assert response.allowed is False
    assert response.reason == "Número no autorizado para este agente"
    service._get_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_governance_fallback_is_explicitly_warned(caplog):
    user = SimpleNamespace(
        id=uuid4(),
        name="Legacy identity",
        is_active=True,
        has_all_area_access=False,
    )
    service = GovernanceService()
    service._get_user = AsyncMock(return_value=user)

    response = await service.check_access(
        object(),
        AccessCheckRequest(request_id="legacy-access", phone_number="redacted"),
    )

    assert response.allowed is True
    assert "legacy_governance_access_without_agent_scope" in caplog.text
    assert "redacted" not in caplog.text


@pytest.mark.asyncio
async def test_agent_document_grants_do_not_fall_back_to_global_policy():
    user_id = uuid4()
    agent_id = uuid4()
    area_id = uuid4()
    binding = SimpleNamespace(is_active=True, has_all_area_access=False)
    db = _SequenceDb(
        _ScalarResult(value=binding),
        _ScalarResult(values=[area_id]),
    )

    assert await get_user_area_ids(db, user_id, agent_id) == {area_id}

    missing_binding_db = _SequenceDb(_ScalarResult(value=None))
    assert await get_user_area_ids(missing_binding_db, user_id, uuid4()) == set()


@pytest.mark.asyncio
async def test_agent_user_area_assignment_rejects_area_owned_by_another_agent():
    foreign_area_id = uuid4()
    db = _SequenceDb(
        _ScalarResult(value=None),
        _ScalarResult(values=[]),
    )

    with pytest.raises(ValueError, match="not assigned to this agent"):
        await AgentResourceService()._sync_authorized_user_areas(
            db,
            agent_id=uuid4(),
            user_id=uuid4(),
            raw_area_ids=[str(foreign_area_id)],
        )
