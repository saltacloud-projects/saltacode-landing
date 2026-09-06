"""Schema-level guards for commercial opportunities and authoritative quotes."""

from app.models.opportunity import (
    FollowUpTask,
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.quote import QuoteRequest, QuoteVersion


def _constraint_names(model) -> set[str | None]:
    return {constraint.name for constraint in model.__table__.constraints}


def _foreign_key_ondelete(model, column_name: str) -> str | None:
    foreign_key = next(iter(model.__table__.columns[column_name].foreign_keys))
    return foreign_key.ondelete


def test_commercial_dossier_preserves_history_and_chat_ownership() -> None:
    assert _foreign_key_ondelete(Opportunity, "contact_id") == "RESTRICT"
    assert _foreign_key_ondelete(OpportunityStageEvent, "opportunity_id") == "RESTRICT"
    assert (
        _foreign_key_ondelete(OpportunityOwnershipEvent, "opportunity_id") == "RESTRICT"
    )
    assert _foreign_key_ondelete(FollowUpTask, "opportunity_id") == "RESTRICT"
    assert _foreign_key_ondelete(QuoteRequest, "opportunity_id") == "RESTRICT"
    assert _foreign_key_ondelete(QuoteVersion, "quote_request_id") == "RESTRICT"
    assert (
        _foreign_key_ondelete(OpportunityConversation, "conversation_id") == "SET NULL"
    )
    assert OpportunityConversation.__table__.columns.conversation_id.nullable is True
    assert "agent_id" not in OpportunityConversation.__table__.columns


def test_opportunity_and_follow_up_have_optimistic_ownership_guards() -> None:
    assert Opportunity.__table__.columns.control_version.default.arg == 0
    assert Opportunity.__table__.columns.control_version.server_default.arg == "0"
    assert FollowUpTask.__table__.columns.state_version.default.arg == 0
    assert FollowUpTask.__table__.columns.state_version.server_default.arg == "0"
    assert "uq_opportunity_stage_event_version" in _constraint_names(
        OpportunityStageEvent
    )
    assert "uq_opportunity_ownership_event_version" in _constraint_names(
        OpportunityOwnershipEvent
    )
    assert "consent_record_id" in FollowUpTask.__table__.columns


def test_quote_versions_are_immutable_and_authority_evidence_is_required() -> None:
    version_columns = QuoteVersion.__table__.columns
    version_constraints = _constraint_names(QuoteVersion)
    request_constraints = _constraint_names(QuoteRequest)

    assert "updated_at" not in version_columns
    assert "content" not in version_columns
    assert "price" not in version_columns
    assert "ck_quote_version_authority_evidence" in version_constraints
    assert "ck_quote_version_content_hash" in version_constraints
    assert "ck_quote_version_issued_before_recorded" in version_constraints
    assert "ck_quote_request_failure_reason" in request_constraints
