"""Schema-level guards for the auditable meeting aggregate."""

from app.models.meeting import Meeting, MeetingEvent, MeetingSlot


def _constraint_names(model) -> set[str | None]:
    return {constraint.name for constraint in model.__table__.constraints}


def _foreign_key_ondelete(model, column_name: str) -> str | None:
    foreign_key = next(iter(model.__table__.columns[column_name].foreign_keys))
    return foreign_key.ondelete


def test_meeting_ownership_is_derived_and_conversation_can_expire() -> None:
    assert "assigned_agent_id" not in Meeting.__table__.columns
    assert _foreign_key_ondelete(Meeting, "opportunity_id") == "RESTRICT"
    assert _foreign_key_ondelete(Meeting, "conversation_id") == "SET NULL"
    assert Meeting.__table__.columns.conversation_id.nullable is True
    assert Meeting.__table__.columns.state_version.default.arg == 0
    assert Meeting.__table__.columns.proposal_version.default.arg == 0


def test_slots_and_events_are_append_only_evidence_shapes() -> None:
    assert "updated_at" not in MeetingSlot.__table__.columns
    assert "updated_at" not in MeetingEvent.__table__.columns
    assert _foreign_key_ondelete(MeetingSlot, "meeting_id") == "RESTRICT"
    assert _foreign_key_ondelete(MeetingEvent, "meeting_id") == "RESTRICT"
    assert _foreign_key_ondelete(MeetingEvent, "actor_admin_id") == "RESTRICT"
    assert _foreign_key_ondelete(MeetingEvent, "actor_agent_id") == "RESTRICT"
    assert "uq_meeting_slot_proposal_position" in _constraint_names(MeetingSlot)
    assert "uq_meeting_event_state_version" in _constraint_names(MeetingEvent)
    assert "uq_meeting_event_idempotency" in _constraint_names(MeetingEvent)
    assert "ck_meeting_event_manual_evidence" in _constraint_names(MeetingEvent)
