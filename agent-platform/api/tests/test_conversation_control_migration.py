"""Schema and revision guards for conversation control."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.conversation_control import ConversationControlEvent
from app.models.platform import ChatConversation, ChatExecution


def test_conversation_control_migration_precedes_the_outbound_head():
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic-platform.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["f6a0b2c4d789"]
    assert scripts.get_revision("d7e8f9a0b1c2").down_revision == "c6d7e8f9a0b1"
    assert scripts.get_revision("7e702862958d").down_revision == "d7e8f9a0b1c2"


def test_control_metadata_contains_required_constraints_and_fields():
    conversation_columns = ChatConversation.__table__.columns
    execution_columns = ChatExecution.__table__.columns
    event_constraints = {
        constraint.name for constraint in ConversationControlEvent.__table__.constraints
    }

    assert conversation_columns.control_mode.default.arg == "automated"
    assert conversation_columns.control_version.default.arg == 0
    assert conversation_columns.assigned_admin_id.nullable is True
    assert execution_columns.control_version.default.arg == 0
    assert "updated_at" not in ConversationControlEvent.__table__.columns
    assert "uq_conversation_control_event_version" in event_constraints
    assert "ck_conversation_control_event_type" in event_constraints
