"""Conversation retention policy tests."""

import uuid
from datetime import datetime, timezone

import pytest

from app.services.retention import purge_expired_conversations


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _Session:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_purge_applies_each_agent_retention_policy():
    first = uuid.uuid4()
    second = uuid.uuid4()
    db = _Session(
        [
            _Result([(first, 30), (second, 90)]),
            _Result([uuid.uuid4(), uuid.uuid4()]),
            _Result([uuid.uuid4()]),
        ]
    )

    deleted = await purge_expired_conversations(
        db, now=datetime(2026, 8, 27, tzinfo=timezone.utc)
    )

    assert deleted == 3
    assert db.commits == 1
    assert len(db.statements) == 3
    assert all(
        "chat_conversations" in str(statement) for statement in db.statements[1:]
    )
    assert all("updated_at" in str(statement) for statement in db.statements[1:])


@pytest.mark.asyncio
async def test_purge_commits_when_no_profiles_have_retention():
    db = _Session([_Result([])])

    assert await purge_expired_conversations(db) == 0
    assert db.commits == 1
    assert len(db.statements) == 1
