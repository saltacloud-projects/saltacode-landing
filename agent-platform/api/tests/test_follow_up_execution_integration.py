"""PostgreSQL coverage for fail-closed commercial follow-up execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, engine
from app.models.agent_profile import AgentProfile
from app.models.agent_runtime import ChannelAgentRoute, ChannelConnection
from app.models.commercial_automation_policy import CommercialAutomationPolicy
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.opportunity import Opportunity, OpportunityConversation
from app.models.outbound import OutboundMessage
from app.models.platform import ChannelIdentity, ChatConversation, Principal
from app.models.quote import QuoteRequest, QuoteVersion
from app.services.commercial.consents import (
    ConsentAction,
    ConsentPurpose,
    ConsentService,
)
from app.services.commercial.follow_up_execution import FollowUpExecutionService
from app.services.commercial.follow_ups import (
    FollowUpService,
    InvalidFollowUpCommandError,
)
from app.services.outbound_follow_up import FollowUpDispatchAuthorizationService

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _Context:
    agent_id: UUID
    principal_id: UUID
    source_conversation_id: UUID
    delivery_conversation_id: UUID
    contact_id: UUID
    point_id: UUID
    consent_id: UUID
    opportunity_id: UUID
    task_id: UUID
    policy_id: UUID
    identity_ids: tuple[UUID, UUID]
    route_ids: tuple[UUID, UUID]
    connection_ids: tuple[UUID, UUID]


class _FakeCrypto:
    def decrypt(self, _ciphertext: str) -> str:
        return "+54 9 387 000 0000"


@pytest.fixture
async def follow_up_context() -> _Context:
    context = await _create_context()
    try:
        yield context
    finally:
        await _cleanup(context)
        await engine.dispose()


def _service() -> FollowUpExecutionService:
    return FollowUpExecutionService(crypto=_FakeCrypto())


@pytest.mark.asyncio
async def test_claim_enqueues_cross_channel_once_without_private_event_payload(
    follow_up_context,
):
    context = follow_up_context
    now = datetime.now(UTC)
    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await service.claim_next(
                db,
                worker_id="follow-up-cross-channel",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await service.enqueue_claim(db, claim=claim, now=now)
    assert result.processed is True
    assert result.safe_code is None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            task = await db.get(FollowUpTask, context.task_id)
            assert task is not None
            outbound = await db.get(OutboundMessage, task.outbound_message_id)
            assert outbound is not None
            await FollowUpDispatchAuthorizationService(crypto=_FakeCrypto()).revalidate(
                db, message=outbound
            )

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "dispatch_queued"
        assert task.attempts == 1
        assert task.executed_consent_record_id == context.consent_id
        assert task.outbound_message_id is not None
        outbound = await db.get(OutboundMessage, task.outbound_message_id)
        assert outbound is not None
        assert outbound.conversation_id == context.delivery_conversation_id
        assert outbound.channel == "whatsapp"
        assert outbound.payload_json == {
            "text": (
                "Hola, retomamos tu consulta para saber si necesitás ayuda con el "
                "próximo paso."
            )
        }
        events = list(
            (
                await db.execute(
                    select(FollowUpTaskEvent)
                    .where(FollowUpTaskEvent.task_id == task.id)
                    .order_by(FollowUpTaskEvent.state_version)
                )
            )
            .scalars()
            .all()
        )
        assert [event.to_status for event in events[-2:]] == [
            "in_progress",
            "dispatch_queued",
        ]
        private_values = (
            "secret@example.invalid",
            "5493870000000",
            "Internal sales note",
        )
        audit_text = " ".join(
            (event.safe_code or "")
            + event.command_hash
            + event.idempotency_key
            + event.correlation_id
            for event in events
        )
        assert all(value not in audit_text for value in private_values)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            duplicate = await service.enqueue_claim(db, claim=claim, now=now)
        assert duplicate.processed is False
        outbound_count = (
            (
                await db.execute(
                    select(OutboundMessage).where(
                        OutboundMessage.agent_id == context.agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(outbound_count) == 1


@pytest.mark.asyncio
async def test_review_required_head_blocks_only_its_fifo(follow_up_context):
    context = follow_up_context
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            head = await db.get(FollowUpTask, context.task_id)
            assert head is not None
            head.status = "review_required"
            head.review_required_at = now
            head.last_safe_code = "manual_review_required"
            head.due_at = now - timedelta(minutes=20)
            blocked = _copy_task(
                head,
                due_at=now - timedelta(minutes=10),
                fifo_key=head.fifo_key,
            )
            independent = _copy_task(
                head,
                due_at=now - timedelta(minutes=5),
                fifo_key=f"independent:{uuid4()}",
            )
            blocked.status = "scheduled"
            blocked.review_required_at = None
            blocked.last_safe_code = None
            independent.status = "scheduled"
            independent.review_required_at = None
            independent.last_safe_code = None
            db.add_all([blocked, independent])

    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await _service().claim_next(
                db,
                worker_id="follow-up-fifo",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is not None
    assert claim.task_id == independent.id

    async with AsyncSessionLocal() as db:
        blocked_stored = await db.get(FollowUpTask, blocked.id)
        assert blocked_stored is not None
        assert blocked_stored.status == "scheduled"
        assert blocked_stored.attempts == 0


@pytest.mark.asyncio
async def test_expired_lease_requires_review_without_retry(follow_up_context):
    context = follow_up_context
    now = datetime.now(UTC)
    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await service.claim_next(
                db,
                worker_id="follow-up-expired",
                lease_duration=timedelta(seconds=30),
                now=now,
            )
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            recovered = await service.recover_expired_leases(
                db,
                worker_id="follow-up-recovery",
                now=now + timedelta(seconds=31),
            )
    assert recovered == 1

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "review_required"
        assert task.attempts == 1
        assert task.last_safe_code == "follow_up_lease_expired"
        async with db.begin_nested():
            retried = await service.claim_next(
                db,
                worker_id="follow-up-retry",
                lease_duration=timedelta(minutes=2),
                now=now + timedelta(minutes=1),
            )
        assert retried is None


@pytest.mark.asyncio
async def test_quiet_hours_defer_without_consuming_attempt(follow_up_context):
    context = follow_up_context
    now = datetime(2026, 9, 6, 6, tzinfo=UTC)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            policy = await db.get(CommercialAutomationPolicy, context.policy_id)
            task = await db.get(FollowUpTask, context.task_id)
            assert policy is not None
            assert task is not None
            policy.timezone = "America/Argentina/Salta"
            policy.quiet_hours_start = time(22)
            policy.quiet_hours_end = time(8)
            task.due_at = now - timedelta(minutes=1)
            task.available_at = task.due_at

    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await _service().claim_next(
                db,
                worker_id="follow-up-quiet",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is None

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "scheduled"
        assert task.attempts == 0
        assert task.available_at == datetime(2026, 9, 6, 11, tzinfo=UTC)
        assert task.last_safe_code == "follow_up_quiet_hours"


@pytest.mark.asyncio
async def test_policy_and_attempt_limits_fail_closed(follow_up_context):
    context = follow_up_context
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            policy = await db.get(CommercialAutomationPolicy, context.policy_id)
            task = await db.get(FollowUpTask, context.task_id)
            assert policy is not None
            assert task is not None
            policy.version += 1

    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await _service().claim_next(
                db,
                worker_id="follow-up-policy-change",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is None

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "review_required"
        assert task.last_safe_code == "follow_up_policy_changed"
        assert task.attempts == 0


@pytest.mark.asyncio
async def test_scheduling_enforces_agent_pending_limit(follow_up_context):
    context = follow_up_context
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            policy = await db.get(CommercialAutomationPolicy, context.policy_id)
            assert policy is not None
            policy.max_pending_tasks = 1
            db.add(
                OpportunityConversation(
                    opportunity_id=context.opportunity_id,
                    conversation_id=context.source_conversation_id,
                    linked_by_agent_id=context.agent_id,
                    correlation_id=f"follow-up-link-{uuid4().hex}",
                    idempotency_key=f"follow-up-link-{uuid4().hex}",
                    command_hash="9" * 64,
                )
            )

    async with AsyncSessionLocal() as db:
        with pytest.raises(
            InvalidFollowUpCommandError,
            match="pending task limit reached",
        ):
            async with db.begin():
                await FollowUpService().schedule(
                    db,
                    opportunity_id=context.opportunity_id,
                    actor_agent_id=context.agent_id,
                    actor_operator_id=None,
                    contact_point_id=context.point_id,
                    kind="commercial_follow_up",
                    due_at=now + timedelta(days=1),
                    note=None,
                    correlation_id=f"follow-up-limit-{uuid4().hex}",
                    idempotency_key=f"follow-up-limit-{uuid4().hex}",
                    conversation_id=context.source_conversation_id,
                    target_channel="whatsapp",
                    now=now,
                )


@pytest.mark.asyncio
async def test_attempt_limit_requires_review_without_claim(follow_up_context):
    context = follow_up_context
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            task = await db.get(FollowUpTask, context.task_id)
            assert task is not None
            task.attempts = task.max_attempts

    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await _service().claim_next(
                db,
                worker_id="follow-up-attempt-limit",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is None

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "review_required"
        assert task.attempts == task.max_attempts
        assert task.last_safe_code == "follow_up_attempt_limit_reached"


@pytest.mark.parametrize("limit", ["min_interval", "daily"])
@pytest.mark.asyncio
async def test_execution_rate_limits_defer_without_consuming_attempt(
    follow_up_context,
    limit,
):
    context = follow_up_context
    now = datetime.now(UTC).replace(microsecond=0)
    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            policy = await db.get(CommercialAutomationPolicy, context.policy_id)
            assert policy is not None
            policy.min_interval_seconds = 3_600 if limit == "min_interval" else 0
            policy.max_daily_tasks = 1 if limit == "daily" else 25

    async with AsyncSessionLocal() as db:
        async with db.begin():
            first_claim = await service.claim_next(
                db,
                worker_id=f"follow-up-rate-{limit}",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert first_claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            first = await db.get(FollowUpTask, context.task_id)
            assert first is not None
            first.status = "completed"
            first.completed_at = now
            first.lease_owner = None
            first.lease_expires_at = None
            second = _copy_task(
                first,
                due_at=now - timedelta(minutes=1),
                fifo_key=(
                    f"independent:{uuid4()}" if limit == "daily" else first.fifo_key
                ),
            )
            db.add(second)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            second_claim = await service.claim_next(
                db,
                worker_id=f"follow-up-rate-next-{limit}",
                lease_duration=timedelta(minutes=2),
                now=now + timedelta(seconds=1),
            )
    assert second_claim is None

    async with AsyncSessionLocal() as db:
        stored = await db.get(FollowUpTask, second.id)
        assert stored is not None
        assert stored.status == "scheduled"
        assert stored.attempts == 0
        assert stored.last_safe_code == (
            "follow_up_min_interval"
            if limit == "min_interval"
            else "follow_up_daily_limit"
        )
        assert stored.available_at > now


@pytest.mark.asyncio
async def test_revoked_consent_after_claim_prevents_enqueue(follow_up_context):
    context = follow_up_context
    now = datetime.now(UTC)
    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await service.claim_next(
                db,
                worker_id="follow-up-consent",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is not None

    async with AsyncSessionLocal() as db:
        await ConsentService().record(
            db,
            agent_id=context.agent_id,
            principal_id=context.principal_id,
            contact_id=context.contact_id,
            contact_point_id=context.point_id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.REVOKE,
            policy_version="commercial-v1",
            channel="web",
            target_channel="whatsapp",
            locale="es-AR",
            source_conversation_id=context.source_conversation_id,
            source_channel_identity_id=context.identity_ids[0],
            actor_admin_id=None,
            correlation_id=f"revoke-{uuid4().hex}",
            idempotency_key=f"revoke-{uuid4().hex}",
            occurred_at=now + timedelta(seconds=1),
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await service.enqueue_claim(
                db,
                claim=claim,
                now=now + timedelta(seconds=2),
            )
    assert result.safe_code == "follow_up_consent_missing"

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "review_required"
        outbound = (
            (
                await db.execute(
                    select(OutboundMessage).where(
                        OutboundMessage.agent_id == context.agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert outbound == []


@pytest.mark.parametrize(
    ("field", "safe_code"),
    [
        ("control_version", "follow_up_control_changed"),
        ("automation_version", "follow_up_automation_changed"),
    ],
)
@pytest.mark.asyncio
async def test_conversation_epoch_change_after_claim_requires_review(
    follow_up_context,
    field,
    safe_code,
):
    context = follow_up_context
    now = datetime.now(UTC)
    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await service.claim_next(
                db,
                worker_id=f"follow-up-{field}",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            source = await db.get(ChatConversation, context.source_conversation_id)
            assert source is not None
            setattr(source, field, getattr(source, field) + 1)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await service.enqueue_claim(db, claim=claim, now=now)
    assert result.safe_code == safe_code


@pytest.mark.asyncio
async def test_unsupported_target_channel_never_creates_fake_delivery(
    follow_up_context,
):
    context = follow_up_context
    now = datetime.now(UTC)
    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            task = await db.get(FollowUpTask, context.task_id)
            consent = await db.get(ConsentRecord, context.consent_id)
            assert task is not None
            assert consent is not None
            task.target_channel = "instagram_dm"
            consent.target_channel = "instagram_dm"

    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await service.claim_next(
                db,
                worker_id="follow-up-unsupported",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await service.enqueue_claim(db, claim=claim, now=now)
    assert result.safe_code == "follow_up_channel_unsupported"

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "review_required"
        outbound = (
            (
                await db.execute(
                    select(OutboundMessage).where(
                        OutboundMessage.agent_id == context.agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert outbound == []


@pytest.mark.asyncio
async def test_proposal_reminder_revalidates_authoritative_quote_ownership(
    follow_up_context,
):
    context = follow_up_context
    now = datetime.now(UTC)
    suffix = uuid4().hex
    async with AsyncSessionLocal() as db:
        async with db.begin():
            other_opportunity = Opportunity(
                contact_id=context.contact_id,
                created_by_agent_id=context.agent_id,
                assigned_agent_id=context.agent_id,
                stage="qualified",
                control_version=0,
                title="Different quote owner",
                correlation_id=f"different-quote-{suffix}",
                idempotency_key=f"different-quote-{suffix}",
                command_hash="e" * 64,
            )
            db.add(other_opportunity)
            await db.flush()
            request = QuoteRequest(
                opportunity_id=other_opportunity.id,
                requested_by_agent_id=context.agent_id,
                status="issued",
                state_version=1,
                requirements_json={},
                correlation_id=f"quote-request-{suffix}",
                idempotency_key=f"quote-request-{suffix}",
                command_hash="f" * 64,
            )
            db.add(request)
            await db.flush()
            version = QuoteVersion(
                quote_request_id=request.id,
                version=1,
                status="issued",
                authority_name="test-authority",
                authority_version="v1",
                external_reference=f"quote-{suffix}",
                content_hash="1" * 64,
                correlation_id=f"quote-version-{suffix}",
                idempotency_key=f"quote-version-{suffix}",
                command_hash="2" * 64,
                issued_at=now,
                created_at=now,
            )
            db.add(version)
            await db.flush()
            task = await db.get(FollowUpTask, context.task_id)
            assert task is not None
            task.kind = "proposal_reminder"
            task.quote_version_id = version.id

    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await service.claim_next(
                db,
                worker_id="follow-up-quote",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is not None

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await service.enqueue_claim(db, claim=claim, now=now)
    assert result.safe_code == "follow_up_quote_evidence_changed"

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == "review_required"
        assert task.outbound_message_id is None


@pytest.mark.parametrize(
    ("outbound_status", "expected_status", "safe_code"),
    [
        ("accepted", "completed", None),
        ("failed", "review_required", "follow_up_outbound_failed"),
        ("cancelled", "review_required", "follow_up_outbound_cancelled"),
        (
            "delivery_unknown",
            "review_required",
            "follow_up_delivery_unknown",
        ),
    ],
)
@pytest.mark.asyncio
async def test_outbound_outcome_reconciliation_is_fail_closed(
    follow_up_context,
    outbound_status,
    expected_status,
    safe_code,
):
    context = follow_up_context
    now = datetime.now(UTC)
    service = _service()
    async with AsyncSessionLocal() as db:
        async with db.begin():
            claim = await service.claim_next(
                db,
                worker_id=f"follow-up-reconcile-{outbound_status}",
                lease_duration=timedelta(minutes=2),
                now=now,
            )
    assert claim is not None
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await service.enqueue_claim(db, claim=claim, now=now)
            task = await db.get(FollowUpTask, context.task_id)
            assert task is not None
            outbound = await db.get(OutboundMessage, task.outbound_message_id)
            assert outbound is not None
            outbound.status = outbound_status
            if outbound_status == "accepted":
                outbound.provider_message_id = "wamid.follow-up"
                outbound.accepted_at = now
                task.executed_consent_record_id = context.consent_id

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await service.reconcile_next(
                db,
                worker_id="follow-up-reconciler",
                now=now + timedelta(seconds=1),
            )
    assert result.processed is True
    assert result.safe_code == safe_code

    async with AsyncSessionLocal() as db:
        task = await db.get(FollowUpTask, context.task_id)
        assert task is not None
        assert task.status == expected_status
        assert task.last_safe_code == safe_code


def _copy_task(
    source: FollowUpTask,
    *,
    due_at: datetime,
    fifo_key: str | None,
) -> FollowUpTask:
    suffix = uuid4().hex
    return FollowUpTask(
        opportunity_id=source.opportunity_id,
        conversation_id=source.conversation_id,
        fifo_key=fifo_key,
        target_channel=source.target_channel,
        contact_point_id=source.contact_point_id,
        consent_record_id=source.consent_record_id,
        assigned_agent_id=source.assigned_agent_id,
        assigned_operator_id=source.assigned_operator_id,
        kind="commercial_follow_up",
        status="scheduled",
        state_version=0,
        scheduled_control_version=source.scheduled_control_version,
        scheduled_automation_version=source.scheduled_automation_version,
        scheduled_policy_version=source.scheduled_policy_version,
        due_at=due_at,
        available_at=due_at,
        attempts=0,
        max_attempts=3,
        note="Internal sales note",
        correlation_id=f"follow-up-copy-{suffix}",
        idempotency_key=f"follow-up-copy-{suffix}",
        command_hash="d" * 64,
        created_at=due_at - timedelta(minutes=1),
    )


async def _create_context() -> _Context:
    suffix = uuid4().hex
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        agent = AgentProfile(
            name="Follow-up execution agent",
            slug=f"follow-up-execution-{suffix}",
            version=1,
            is_active=True,
            is_public=False,
            retention_days=30,
            prompt_identity="test",
            prompt_domain="test",
            prompt_guardrails="test",
            unauthorized_message="unauthorized",
            error_message="error",
        )
        web_connection = ChannelConnection(
            name="Follow-up web connection",
            slug=f"follow-up-web-{suffix}",
            channel="web",
            adapter_key="web_builtin",
            version=0,
            external_account_id=f"web-{suffix}",
            settings_json={},
            is_active=True,
        )
        whatsapp_connection = ChannelConnection(
            name="Follow-up WhatsApp connection",
            slug=f"follow-up-whatsapp-{suffix}",
            channel="whatsapp",
            adapter_key="meta_whatsapp_cloud",
            version=0,
            external_account_id=f"whatsapp-{suffix}",
            settings_json={},
            encrypted_credentials="opaque-test-credentials",
            is_active=True,
        )
        principal = Principal(display_name="Follow-up execution principal")
        db.add_all([agent, web_connection, whatsapp_connection, principal])
        await db.flush()
        web_route = ChannelAgentRoute(
            channel="web",
            version=0,
            route_key=f"follow-up-web-{suffix}",
            channel_connection_id=web_connection.id,
            agent_id=agent.id,
            is_active=True,
        )
        whatsapp_route = ChannelAgentRoute(
            channel="whatsapp",
            version=0,
            route_key=f"follow-up-whatsapp-{suffix}",
            channel_connection_id=whatsapp_connection.id,
            agent_id=agent.id,
            is_active=True,
        )
        web_identity = ChannelIdentity(
            principal_id=principal.id,
            channel="web",
            route_key=web_route.route_key,
            external_subject=str(uuid4()),
            verified=True,
        )
        whatsapp_identity = ChannelIdentity(
            principal_id=principal.id,
            channel="whatsapp",
            route_key=whatsapp_route.route_key,
            external_subject="5493870000000",
            verified=True,
        )
        db.add_all([web_route, whatsapp_route, web_identity, whatsapp_identity])
        await db.flush()
        source = ChatConversation(
            agent_id=agent.id,
            automation_agent_id=agent.id,
            automation_version=0,
            principal_id=principal.id,
            channel="web",
            external_thread_id=web_identity.external_subject,
            route_key=web_route.route_key,
            channel_route_id=web_route.id,
            transcript_consent=True,
        )
        delivery = ChatConversation(
            agent_id=agent.id,
            automation_agent_id=agent.id,
            automation_version=0,
            principal_id=principal.id,
            channel="whatsapp",
            external_thread_id=whatsapp_identity.external_subject,
            route_key=whatsapp_route.route_key,
            channel_route_id=whatsapp_route.id,
            transcript_consent=True,
        )
        contact = Contact(
            principal_id=principal.id,
            created_by_agent_id=agent.id,
            status="active",
        )
        policy = CommercialAutomationPolicy(
            agent_id=agent.id,
            is_enabled=True,
            allowed_kinds=["commercial_follow_up", "proposal_reminder"],
            timezone="UTC",
            min_interval_seconds=0,
            max_attempts=3,
            max_daily_tasks=25,
            max_pending_tasks=100,
            version=0,
        )
        db.add_all([source, delivery, contact, policy])
        await db.flush()
        point = ContactPoint(
            contact_id=contact.id,
            kind="phone",
            ciphertext="gAAAAA" + ("x" * 80),
            lookup_hmac="a" * 64,
            masked_value="+54*******0000",
            verification_status="verified",
            verified_at=now,
            source_conversation_id=source.id,
            source_channel_identity_id=web_identity.id,
        )
        opportunity = Opportunity(
            contact_id=contact.id,
            created_by_agent_id=agent.id,
            assigned_agent_id=agent.id,
            stage="qualified",
            control_version=0,
            title="Follow-up execution opportunity",
            correlation_id=f"follow-up-opportunity-{suffix}",
            idempotency_key=f"follow-up-opportunity-{suffix}",
            command_hash="a" * 64,
        )
        db.add_all([point, opportunity])
        await db.flush()
        consent = ConsentRecord(
            principal_id=principal.id,
            contact_id=contact.id,
            contact_point_id=point.id,
            agent_id=agent.id,
            purpose=ConsentPurpose.COMMERCIAL_FOLLOW_UP,
            action=ConsentAction.GRANT,
            policy_version="commercial-v1",
            channel="web",
            target_channel="whatsapp",
            locale="es-AR",
            source_conversation_id=source.id,
            source_channel_identity_id=web_identity.id,
            correlation_id=f"follow-up-consent-{suffix}",
            idempotency_key=f"follow-up-consent-{suffix}",
            command_hash="b" * 64,
            occurred_at=now - timedelta(minutes=30),
        )
        db.add(consent)
        await db.flush()
        task = FollowUpTask(
            opportunity_id=opportunity.id,
            conversation_id=source.id,
            fifo_key=f"conversation:{source.id}",
            target_channel="whatsapp",
            contact_point_id=point.id,
            consent_record_id=consent.id,
            assigned_agent_id=agent.id,
            kind="commercial_follow_up",
            status="scheduled",
            state_version=0,
            scheduled_control_version=0,
            scheduled_automation_version=0,
            scheduled_policy_version=0,
            due_at=now - timedelta(minutes=10),
            available_at=now - timedelta(minutes=10),
            attempts=0,
            max_attempts=3,
            note="Internal sales note",
            correlation_id=f"follow-up-task-{suffix}",
            idempotency_key=f"follow-up-task-{suffix}",
            command_hash="c" * 64,
            created_at=now - timedelta(minutes=20),
        )
        db.add(task)
        await db.commit()
        return _Context(
            agent_id=agent.id,
            principal_id=principal.id,
            source_conversation_id=source.id,
            delivery_conversation_id=delivery.id,
            contact_id=contact.id,
            point_id=point.id,
            consent_id=consent.id,
            opportunity_id=opportunity.id,
            task_id=task.id,
            policy_id=policy.id,
            identity_ids=(web_identity.id, whatsapp_identity.id),
            route_ids=(web_route.id, whatsapp_route.id),
            connection_ids=(web_connection.id, whatsapp_connection.id),
        )


async def _cleanup(context: _Context) -> None:
    async with AsyncSessionLocal() as db:
        opportunity_ids = select(Opportunity.id).where(
            Opportunity.contact_id == context.contact_id
        )
        task_ids = select(FollowUpTask.id).where(
            FollowUpTask.opportunity_id.in_(opportunity_ids)
        )
        await db.execute(
            delete(FollowUpTaskEvent).where(FollowUpTaskEvent.task_id.in_(task_ids))
        )
        await db.execute(
            delete(FollowUpTask).where(FollowUpTask.opportunity_id.in_(opportunity_ids))
        )
        await db.execute(
            delete(OutboundMessage).where(OutboundMessage.agent_id == context.agent_id)
        )
        await db.execute(
            delete(ConsentRecord).where(ConsentRecord.contact_id == context.contact_id)
        )
        quote_request_ids = select(QuoteRequest.id).where(
            QuoteRequest.opportunity_id.in_(opportunity_ids)
        )
        await db.execute(
            delete(QuoteVersion).where(
                QuoteVersion.quote_request_id.in_(quote_request_ids)
            )
        )
        await db.execute(
            delete(QuoteRequest).where(QuoteRequest.opportunity_id.in_(opportunity_ids))
        )
        await db.execute(
            delete(OpportunityConversation).where(
                OpportunityConversation.opportunity_id.in_(opportunity_ids)
            )
        )
        await db.execute(delete(Opportunity).where(Opportunity.id.in_(opportunity_ids)))
        await db.execute(delete(Contact).where(Contact.id == context.contact_id))
        await db.execute(
            delete(ChatConversation).where(
                ChatConversation.id.in_(
                    (
                        context.source_conversation_id,
                        context.delivery_conversation_id,
                    )
                )
            )
        )
        await db.execute(
            delete(ChannelIdentity).where(ChannelIdentity.id.in_(context.identity_ids))
        )
        await db.execute(delete(Principal).where(Principal.id == context.principal_id))
        await db.execute(
            delete(CommercialAutomationPolicy).where(
                CommercialAutomationPolicy.id == context.policy_id
            )
        )
        await db.execute(
            delete(ChannelAgentRoute).where(ChannelAgentRoute.id.in_(context.route_ids))
        )
        await db.execute(
            delete(ChannelConnection).where(
                ChannelConnection.id.in_(context.connection_ids)
            )
        )
        await db.execute(
            delete(AgentProfile).where(AgentProfile.id == context.agent_id)
        )
        await db.commit()
