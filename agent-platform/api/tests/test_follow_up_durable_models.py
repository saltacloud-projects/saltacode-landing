"""Schema guards for durable follow-up work and fail-closed policy."""

from app.models.commercial_automation_policy import CommercialAutomationPolicy
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import FollowUpTask as CompatibleFollowUpTask


def _constraint_names(model) -> set[str | None]:
    return {constraint.name for constraint in model.__table__.constraints}


def test_follow_up_aggregate_has_single_compatible_model() -> None:
    assert CompatibleFollowUpTask is FollowUpTask
    assert FollowUpTask.__table__.name == "follow_up_tasks"
    assert FollowUpTaskEvent.__table__.name == "follow_up_task_events"


def test_follow_up_task_fences_dispatch_and_outputs() -> None:
    columns = FollowUpTask.__table__.columns
    constraints = _constraint_names(FollowUpTask)

    for column in (
        "conversation_id",
        "fifo_key",
        "target_channel",
        "scheduled_control_version",
        "scheduled_automation_version",
        "scheduled_policy_version",
        "executed_policy_version",
        "available_at",
        "attempts",
        "max_attempts",
        "lease_owner",
        "lease_expires_at",
        "chat_message_id",
        "outbound_message_id",
        "executed_consent_record_id",
        "last_safe_code",
        "review_required_at",
        "quote_version_id",
    ):
        assert column in columns
    assert "ck_follow_up_task_dispatch_snapshot" in constraints
    assert "ck_follow_up_task_lease_pair" in constraints
    assert "ck_follow_up_task_in_progress_lease" in constraints
    assert "ck_follow_up_task_scheduled_policy_version" in constraints
    assert "ck_follow_up_task_executed_policy_version" in constraints
    assert "ck_follow_up_task_target_channel" in constraints
    assert "ck_follow_up_task_proposal_quote" in constraints
    assert "uq_follow_up_task_chat_message" in constraints
    assert "uq_follow_up_task_outbound_message" in constraints
    conversation_foreign_key = next(iter(columns.conversation_id.foreign_keys))
    assert conversation_foreign_key.ondelete == "RESTRICT"


def test_follow_up_events_are_versioned_and_actor_exact() -> None:
    columns = FollowUpTaskEvent.__table__.columns
    constraints = _constraint_names(FollowUpTaskEvent)

    assert "uq_follow_up_task_event_version" in constraints
    assert "uq_follow_up_task_event_idempotency" in constraints
    assert "ck_follow_up_task_event_actor" in constraints
    assert "ck_follow_up_task_event_snapshot" in constraints
    assert "ck_follow_up_task_event_scheduled_policy_version" in constraints
    assert "ck_follow_up_task_event_executed_policy_version" in constraints
    assert "ck_follow_up_task_event_target_channel" in constraints
    assert "uq_follow_up_task_event_chat_message" in constraints
    assert "uq_follow_up_task_event_outbound_message" in constraints
    actor_admin_foreign_key = next(iter(columns.actor_admin_id.foreign_keys))
    assert actor_admin_foreign_key.ondelete == "RESTRICT"


def test_commercial_automation_policy_defaults_disabled() -> None:
    columns = CommercialAutomationPolicy.__table__.columns
    constraints = _constraint_names(CommercialAutomationPolicy)

    assert columns.is_enabled.default.arg is False
    assert columns.version.default.arg == 0
    assert columns.max_attempts.default.arg == 3
    assert "uq_commercial_automation_policy_agent" in constraints
    assert "ck_commercial_automation_policy_allowed_kinds" in constraints
    assert "ck_commercial_automation_policy_quiet_pair" in constraints
    assert "ck_commercial_automation_policy_limits" in constraints
