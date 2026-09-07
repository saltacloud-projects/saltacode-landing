"""Safe administrative changes used to activate the commercial contact flow."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app import bootstrap
from app.core.database import AsyncSessionLocal
from app.dependencies import get_db
from app.models.agent_profile import AgentProfile
from app.models.audit_log import AuditLog
from app.models.tool_config import ToolConfig
from app.routers.admin import agent_resources, profiles
from app.routers.admin.auth import require_admin
from app.schemas.admin import ProfileUpdate
from app.schemas.tools import ToolExecutionContext
from app.services.tool_policy import ToolPolicyService


def _profile():
    return AgentProfile(
        id=uuid4(),
        name="Advisor",
        slug="advisor",
        version=1,
        is_active=True,
        is_public=True,
        retention_days=30,
        prompt_identity="Configured identity",
        prompt_domain="Configured services",
        prompt_guardrails="Never invent consent",
        unauthorized_message="Access denied",
        error_message="Unavailable",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_profile_update_audits_only_changed_field_names(monkeypatch):
    profile = _profile()
    actor = SimpleNamespace(id=uuid4())
    db = SimpleNamespace(add=Mock(), flush=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(profiles, "_get_or_404", AsyncMock(return_value=profile))
    private_prompt = "Private operating instructions not suitable for audit"

    result = await profiles.update_profile(
        str(profile.id),
        ProfileUpdate(prompt_domain=private_prompt, name=profile.name),
        db,
        actor,
    )

    assert result.prompt_domain == private_prompt
    audit = db.add.call_args.args[0]
    assert isinstance(audit, AuditLog)
    assert audit.agent_id == profile.id
    assert audit.intent == "agent.profile.updated"
    assert audit.status == "success"
    assert audit.extra_metadata == {
        "actor_admin_id": str(actor.id),
        "changed_fields": ["prompt_domain"],
    }
    assert audit.user_message is None
    assert audit.response_preview is None
    assert private_prompt not in str(audit.extra_metadata)


@pytest.mark.asyncio
async def test_noop_profile_update_does_not_invent_a_change(monkeypatch):
    profile = _profile()
    db = SimpleNamespace(add=Mock(), flush=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(profiles, "_get_or_404", AsyncMock(return_value=profile))

    await profiles.update_profile(
        str(profile.id),
        ProfileUpdate(prompt_domain=profile.prompt_domain),
        db,
        SimpleNamespace(id=uuid4()),
    )

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_failed_profile_write_does_not_claim_success(monkeypatch):
    profile = _profile()
    db = SimpleNamespace(add=Mock(), refresh=AsyncMock())
    monkeypatch.setattr(profiles, "_get_or_404", AsyncMock(return_value=profile))
    monkeypatch.setattr(
        profiles,
        "_flush_profile",
        AsyncMock(side_effect=HTTPException(409, "conflict")),
    )

    with pytest.raises(HTTPException):
        await profiles.update_profile(
            str(profile.id),
            ProfileUpdate(prompt_domain="Updated instructions"),
            db,
            SimpleNamespace(id=uuid4()),
        )

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_tool_binding_audit_describes_idempotent_ensure_not_creation(monkeypatch):
    agent_id, tool_id, actor_id = uuid4(), uuid4(), uuid4()
    db = SimpleNamespace(add=Mock())
    monkeypatch.setattr(
        agent_resources, "_agent_or_404", AsyncMock(return_value=agent_id)
    )
    monkeypatch.setattr(
        agent_resources, "_resource_or_404", AsyncMock(return_value=tool_id)
    )
    assign = AsyncMock()
    monkeypatch.setattr(agent_resources.agent_resource_service, "assign_tool", assign)

    for _ in range(2):
        await agent_resources.assign_agent_tool(
            str(agent_id), str(tool_id), db, SimpleNamespace(id=actor_id)
        )

    assert assign.await_count == 2
    for call in db.add.call_args_list:
        audit = call.args[0]
        assert audit.agent_id == agent_id
        assert audit.intent == "agent.tool.binding.ensured"
        assert audit.extra_metadata == {
            "actor_admin_id": str(actor_id),
            "tool_id": str(tool_id),
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["profile", "tool"])
async def test_mutations_still_deny_foreign_agent_before_audit(resource, monkeypatch):
    app = FastAPI()
    app.include_router(profiles.router, prefix="/profiles")
    app.include_router(agent_resources.router, prefix="/agents")
    db = SimpleNamespace(add=Mock())
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id=uuid4(), role="operator"
    )
    access = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "app.routers.admin.auth.admin_agent_access_service.has_permission", access
    )
    agent_id = uuid4()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if resource == "profile":
            response = await client.patch(
                f"/profiles/{agent_id}", json={"prompt_domain": "Not allowed"}
            )
        else:
            response = await client.put(f"/agents/{agent_id}/tools/{uuid4()}")

    assert response.status_code == 403
    assert access.await_args.kwargs["agent_id"] == agent_id
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_preserves_existing_agent_prompts_and_resource_choices(
    monkeypatch,
):
    profile = _profile()
    before = (profile.prompt_identity, profile.prompt_domain, profile.prompt_guardrails)
    existing = [object(), object(), profile]
    existing.extend(object() for _ in bootstrap.DEFAULT_BLOCKS)
    existing.extend([object(), object()])
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda row=row: row)
                for row in existing
            ]
        ),
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    session = AsyncMock()
    session.__aenter__.return_value = db
    monkeypatch.setattr(bootstrap, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(
        bootstrap.settings, "admin_initial_password", "test-only-password"
    )
    monkeypatch.setattr(bootstrap, "bootstrap_admin_agent_grant", AsyncMock())
    monkeypatch.setattr(bootstrap, "bootstrap_operational_config", AsyncMock())
    blocks = AsyncMock()
    areas = AsyncMock()
    tools = AsyncMock()
    monkeypatch.setattr(
        bootstrap.agent_resource_service, "assign_knowledge_block", blocks
    )
    monkeypatch.setattr(bootstrap.agent_resource_service, "assign_document_area", areas)
    monkeypatch.setattr(bootstrap.agent_resource_service, "assign_tool", tools)

    await bootstrap.bootstrap()

    assert (
        profile.prompt_identity,
        profile.prompt_domain,
        profile.prompt_guardrails,
    ) == before
    db.add.assert_not_called()
    blocks.assert_not_awaited()
    areas.assert_not_awaited()
    tools.assert_not_awaited()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_native_contact_binding_and_audits_persist_only_for_the_target_agent():
    profile = _profile()
    profile.slug = f"commercial-audit-{profile.id}"
    actor = SimpleNamespace(id=uuid4())
    tool_name = "commercial_quote_contact_request"
    context = ToolExecutionContext(
        request_id="synthetic-tool-catalog-check",
        channel="web",
        agent_id=str(profile.id),
    )
    policy = ToolPolicyService()
    try:
        async with AsyncSessionLocal() as db:
            db.add(profile)
            await db.commit()
            tool = (
                await db.execute(
                    select(ToolConfig).where(ToolConfig.tool_name == tool_name)
                )
            ).scalar_one()
            assert await policy.available_tools(db, context, {tool_name}) == []

            await profiles.update_profile(
                str(profile.id),
                ProfileUpdate(prompt_domain="Synthetic configured commercial flow"),
                db,
                actor,
            )
            await agent_resources.assign_agent_tool(
                str(profile.id), str(tool.id), db, actor
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            available = await policy.available_tools(db, context, {tool_name})
            assert [item["tool_name"] for item in available] == [tool_name]
            assert (
                await policy.available_tools(
                    db,
                    context.model_copy(update={"agent_id": str(uuid4())}),
                    {tool_name},
                )
                == []
            )
            audits = list(
                (
                    await db.execute(
                        select(AuditLog).where(AuditLog.agent_id == profile.id)
                    )
                ).scalars()
            )
            assert {audit.intent for audit in audits} == {
                "agent.profile.updated",
                "agent.tool.binding.ensured",
            }
            assert all(
                audit.extra_metadata["actor_admin_id"] == str(actor.id)
                for audit in audits
            )
            assert all(audit.user_message is None for audit in audits)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLog).where(AuditLog.agent_id == profile.id))
            await db.execute(delete(AgentProfile).where(AgentProfile.id == profile.id))
            await db.commit()
