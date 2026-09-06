"""Metadata guards for conversation automation assignment persistence."""

from sqlalchemy.schema import CheckConstraint, Index, UniqueConstraint

from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.platform import ChatConversation


def test_conversation_automation_snapshot_is_required_and_versioned() -> None:
    columns = ChatConversation.__table__.columns
    constraints = {
        constraint.name for constraint in ChatConversation.__table__.constraints
    }
    indexes = {index.name for index in ChatConversation.__table__.indexes}

    assert columns.automation_agent_id.nullable is False
    assert columns.automation_agent_id.default.is_callable
    assert columns.automation_version.nullable is False
    assert columns.automation_version.default.arg == 0
    assert str(columns.automation_version.server_default.arg) == "0"
    assert "ck_chat_conversation_automation_version" in constraints
    assert "ix_chat_conversation_automation_status_updated" in indexes


def test_assignment_events_enforce_actor_shape_and_applied_epochs() -> None:
    table = ConversationAutomationAssignmentEvent.__table__
    constraint_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }
    indexes: dict[str, Index] = {index.name: index for index in table.indexes}

    assert "updated_at" not in table.columns
    assert "uq_conversation_automation_assignment_idempotency" in constraint_names
    assert "ck_conversation_automation_assignment_actor" in constraint_names
    assert "ck_conversation_automation_assignment_shape" in constraint_names
    applied_version = indexes["uq_conversation_automation_assignment_applied_version"]
    assert applied_version.unique is True
    assert str(applied_version.dialect_options["postgresql"]["where"]) == "applied"
