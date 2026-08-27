"""Contracts for agent-owned resource bindings and compatibility paths."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.dependencies import get_db
from app.models.agent_profile import AgentProfile
from app.models.agent_resource_binding import (
    AgentKnowledgeBlockBinding,
    AgentOrganizationAreaBinding,
    AgentSourceBinding,
    AgentToolBinding,
)
from app.models.integration_source import IntegrationSource
from app.routers.admin.agent_resources import router as agent_resources_router
from app.services.agent_profile import AgentProfileService
from app.services.knowledge import KnowledgeService
from app.services.rag.retrieval import RagRetrievalService


class _ScalarResult:
    def __init__(self, values):
        self._values = list(values)

    def scalars(self):
        return self

    def all(self):
        return self._values

    def scalar_one_or_none(self):
        return self._values[0] if self._values else None


class _AgentFilteredDb:
    def __init__(self, values_by_agent: dict[UUID, list], legacy_values: list):
        self.values_by_agent = values_by_agent
        self.legacy_values = legacy_values

    async def execute(self, statement):
        values = set(statement.compile().params.values())
        for agent_id, resources in self.values_by_agent.items():
            if agent_id in values:
                return _ScalarResult(resources)
        return _ScalarResult(self.legacy_values)


def test_binding_models_have_cascading_foreign_keys_and_unique_pairs() -> None:
    expected = {
        AgentSourceBinding: {"agent_id", "source_id"},
        AgentToolBinding: {"agent_id", "tool_id"},
        AgentKnowledgeBlockBinding: {"agent_id", "knowledge_block_id"},
        AgentOrganizationAreaBinding: {"agent_id", "area_id"},
    }
    for model, pair in expected.items():
        table = model.__table__
        unique_pairs = {
            frozenset(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert frozenset(pair) in unique_pairs
        assert pair.issubset({index.columns.keys()[0] for index in table.indexes})
        foreign_keys = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        ]
        assert len(foreign_keys) == 2
        assert all(constraint.ondelete == "CASCADE" for constraint in foreign_keys)


def test_agent_resource_api_exposes_all_binding_contracts() -> None:
    app = FastAPI()
    app.include_router(agent_resources_router, prefix="/api/admin/agents")
    contracts = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    for resource in ("sources", "tools", "knowledge-blocks", "document-areas"):
        collection = f"/api/admin/agents/{{agent_id}}/{resource}"
        member = (
            collection
            + "/{"
            + {
                "sources": "source_id",
                "tools": "tool_id",
                "knowledge-blocks": "block_id",
                "document-areas": "area_id",
            }[resource]
            + "}"
        )
        assert (collection, "GET") in contracts
        assert (member, "PUT") in contracts
        assert (member, "DELETE") in contracts


@pytest.mark.asyncio
async def test_knowledge_is_isolated_by_agent_with_legacy_global_fallback() -> None:
    agent_a = uuid4()
    agent_b = uuid4()
    block_a = SimpleNamespace(key="a", sort_order=10, is_enabled=True)
    block_b = SimpleNamespace(key="b", sort_order=20, is_enabled=True)
    db = _AgentFilteredDb({agent_a: [block_a], agent_b: [block_b]}, [block_a, block_b])
    service = KnowledgeService()

    assert await service.get_blocks(db, agent_id=agent_a) == [block_a]
    assert await service.get_blocks(db, agent_id=agent_b) == [block_b]
    assert await service.get_blocks(db) == [block_a, block_b]


@pytest.mark.asyncio
async def test_rag_area_binding_intersects_existing_caller_access(monkeypatch) -> None:
    assigned_area = uuid4()
    caller_area = uuid4()
    settings_row = SimpleNamespace(enabled=True)
    settings_get = AsyncMock(return_value=settings_row)
    assigned_ids = AsyncMock(return_value={assigned_area})
    embed_query = AsyncMock()
    monkeypatch.setattr(
        "app.services.rag.retrieval.rag_settings_service.get", settings_get
    )
    monkeypatch.setattr(
        "app.services.rag.retrieval.agent_resource_service.assigned_area_ids",
        assigned_ids,
    )
    monkeypatch.setattr(
        "app.services.rag.retrieval.embedding_service.embed_query", embed_query
    )

    hits = await RagRetrievalService().search(
        object(),
        query="isolated query",
        user_id=None,
        request_id="rag-isolation",
        agent_id=uuid4(),
        area_ids_override={caller_area},
    )

    assert hits == []
    embed_query.assert_not_awaited()


def test_backfill_assigns_existing_libraries_only_to_configured_default_agent(
    monkeypatch,
) -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations_platform"
        / "versions"
        / "6c9c18a6f821_agent_resource_bindings.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agent_binding_migration", migration_path
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    calls: list[tuple[str, str, str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda statement: calls.append(
            (
                str(statement),
                "",
                "",
                statement.compile().params["default_slug"],
            )
        ),
    )
    migration._backfill_binding(
        "agent_source_bindings",
        "source_id",
        "integration_sources",
        "configured-agent",
    )

    sql, _, _, slug = calls[0]
    assert "CROSS JOIN integration_sources" in sql
    assert "agent_profiles.slug =" in sql
    assert "INSERT INTO agent_profiles" not in sql
    assert slug == "configured-agent"


class _Redis:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def get(self, key):
        return self.values.get(key)

    async def setex(self, key, _ttl, value):
        self.values[key] = value


class _ProfileDb:
    def __init__(self, profiles):
        self.profiles = profiles

    async def execute(self, statement):
        params = set(statement.compile().params.values())
        selected = [
            profile
            for profile in self.profiles
            if profile.slug in params or profile.id in params
        ]
        return _ScalarResult(selected)


@pytest.mark.asyncio
async def test_profile_cache_is_addressed_per_agent() -> None:
    now = datetime.now(timezone.utc)
    profiles = [
        AgentProfile(
            id=uuid4(),
            name=name,
            slug=slug,
            version=1,
            is_active=True,
            is_public=True,
            retention_days=30,
            description=None,
            prompt_identity="identity",
            prompt_domain="domain",
            prompt_guardrails="guardrails",
            unauthorized_message="unauthorized",
            error_message="error",
            created_at=now,
            updated_at=now,
            created_by="test",
        )
        for name, slug in (("Agent A", "agent-a"), ("Agent B", "agent-b"))
    ]
    redis = _Redis()
    service = AgentProfileService()

    assert (
        await service.get_profile(_ProfileDb(profiles), slug="agent-a", redis=redis)
    ).slug == "agent-a"
    assert (
        await service.get_profile(_ProfileDb(profiles), slug="agent-b", redis=redis)
    ).slug == "agent-b"
    assert "agent_profile:slug:agent-a" in redis.values
    assert "agent_profile:slug:agent-b" in redis.values
    assert "agent_profile:active" not in redis.values


class _BindingApiDb:
    def __init__(self, agent_id: UUID, source):
        self.agent_id = agent_id
        self.source = source
        self.binding = None

    async def get(self, model, resource_id):
        if model is AgentProfile and resource_id == self.agent_id:
            return SimpleNamespace(id=self.agent_id)
        if model is IntegrationSource and resource_id == self.source.id:
            return self.source
        return None

    async def execute(self, statement):
        if statement.__visit_name__ == "delete":
            self.binding = None
            return SimpleNamespace(rowcount=1)
        if statement.__visit_name__ == "insert":
            if self.binding is None:
                self.binding = SimpleNamespace(id=uuid4())
            return SimpleNamespace(rowcount=1)
        entity = statement.column_descriptions[0].get("entity")
        if entity is IntegrationSource:
            return _ScalarResult([self.source] if self.binding else [])
        if entity is AgentSourceBinding:
            return _ScalarResult([self.binding.id] if self.binding else [])
        return _ScalarResult([])


@pytest.mark.asyncio
async def test_agent_source_binding_api_is_idempotent_and_reversible() -> None:
    now = datetime.now(timezone.utc)
    agent_id = uuid4()
    source = SimpleNamespace(
        id=uuid4(),
        name="Catalog",
        slug="catalog",
        source_type="http",
        base_url="https://example.test",
        allowed_hosts=["example.test"],
        auth_type="none",
        auth_config={},
        encrypted_credentials=None,
        default_headers={},
        is_active=True,
        is_public=True,
        verify_tls=True,
        allow_private_network=False,
        timeout_seconds=30,
        max_response_bytes=2_000_000,
        created_by="test",
        created_at=now,
        updated_at=now,
    )
    db = _BindingApiDb(agent_id, source)
    app = FastAPI()
    app.include_router(agent_resources_router, prefix="/api/admin/agents")

    async def _db_override():
        yield db

    async def _allow():
        return SimpleNamespace(role="admin")

    app.dependency_overrides[get_db] = _db_override
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for dependency in route.dependant.dependencies:
            if dependency.call is not get_db:
                app.dependency_overrides[dependency.call] = _allow

    path = f"/api/admin/agents/{agent_id}/sources/{source.id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.put(path)).status_code == 204
        assert (await client.put(path)).status_code == 204
        response = await client.get(f"/api/admin/agents/{agent_id}/sources")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(source.id)]
        assert (await client.delete(path)).status_code == 204
        response = await client.get(f"/api/admin/agents/{agent_id}/sources")
        assert response.json() == []
