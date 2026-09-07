"""Independent agent creation, validation, grant, and activation contracts."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.agent_profile import AgentProfile
from app.routers.admin import profiles
from app.schemas.admin import ProfileCreate, ProfileUpdate


def draft(**overrides):
    return ProfileCreate(
        **{
            "name": "Sales advisor",
            "slug": "sales-advisor",
            "prompt_identity": "Introduce yourself as our sales advisor.",
            "prompt_domain": "Answer questions about our documented services.",
            "prompt_guardrails": "Never invent a price or consent.",
            **overrides,
        }
    )


def database(*, existing_slug=None, flush_error=None):
    rows = []

    async def flush():
        if flush_error:
            raise flush_error
        for row in rows:
            row.id = row.id or uuid4()
            row.version = 1
            row.created_at = datetime.now(timezone.utc)
            row.updated_at = row.created_at

    db = SimpleNamespace(
        add=Mock(side_effect=rows.append),
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalar_one_or_none=lambda: existing_slug,
            )
        ),
        flush=AsyncMock(side_effect=flush),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
    )
    return db, rows


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "   "),
        ("slug", "../other-agent"),
        ("slug", "Upper Case"),
        ("slug", "a" * 101),
        ("prompt_identity", "\n "),
        ("prompt_domain", ""),
        ("prompt_guardrails", "\t"),
    ],
)
def test_creation_and_updates_reject_invalid_required_fields(field, value):
    with pytest.raises(ValidationError):
        draft(**{field: value})
    with pytest.raises(ValidationError):
        ProfileUpdate(**{field: value})


def test_agent_draft_trims_required_text_without_inventing_behavior():
    data = draft(name=" Advisor ", slug="advisor_it", prompt_domain=" Services ")
    assert data.name == "Advisor"
    assert data.slug == "advisor_it"
    assert data.prompt_domain == "Services"
    assert data.is_public is False
    assert data.retention_days == 30


@pytest.mark.asyncio
async def test_creation_creates_only_inactive_agent_and_creator_grant(monkeypatch):
    db, rows = database()
    admin = SimpleNamespace(id=uuid4())
    grant = AsyncMock()
    monkeypatch.setattr(profiles.admin_agent_access_service, "ensure_grant", grant)

    result = await profiles.create_profile(draft(), admin, db)

    assert len(rows) == 1
    assert isinstance(rows[0], AgentProfile)
    assert result.is_active is False
    assert result.is_public is False
    assert result.created_by == str(admin.id)
    assert result.prompt_domain == draft().prompt_domain
    grant.assert_awaited_once_with(
        db,
        admin_user_id=admin.id,
        agent_id=rows[0].id,
        permissions=["*"],
        created_by=str(admin.id),
    )


@pytest.mark.asyncio
async def test_duplicate_slug_is_a_conflict_without_creating_agent():
    db, rows = database(existing_slug=uuid4())
    with pytest.raises(HTTPException) as error:
        await profiles.create_profile(draft(), SimpleNamespace(id=uuid4()), db)
    assert error.value.status_code == 409
    assert error.value.detail == "agent_slug_conflict"
    assert not rows


@pytest.mark.asyncio
async def test_concurrent_duplicate_slug_rolls_back_with_safe_conflict(monkeypatch):
    failure = IntegrityError("insert", {}, SimpleNamespace(sqlstate="23505"))
    db, _ = database(flush_error=failure)
    grant = AsyncMock()
    monkeypatch.setattr(profiles.admin_agent_access_service, "ensure_grant", grant)
    with pytest.raises(HTTPException) as error:
        await profiles.create_profile(draft(), SimpleNamespace(id=uuid4()), db)
    assert error.value.status_code == 409
    db.rollback.assert_awaited_once()
    grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_integrity_error_is_not_mislabeled_as_slug_conflict():
    failure = IntegrityError("insert", {}, SimpleNamespace(sqlstate="23502"))
    db, _ = database(flush_error=failure)
    with pytest.raises(IntegrityError):
        await profiles.create_profile(draft(), SimpleNamespace(id=uuid4()), db)


@pytest.mark.asyncio
async def test_activation_does_not_disable_another_agent(monkeypatch):
    db, rows = database()
    first = AgentProfile(**draft(slug="first").model_dump(), is_active=True)
    second = AgentProfile(**draft(slug="second").model_dump(), is_active=False)
    rows.extend([first, second])
    await db.flush()
    monkeypatch.setattr(profiles, "_get_or_404", AsyncMock(return_value=second))
    result = await profiles.activate_profile(str(second.id), db)
    assert result.is_active is True
    assert first.is_active is True
