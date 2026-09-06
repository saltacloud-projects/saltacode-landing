"""Focused policy tests for fail-closed delivery resolution."""

from __future__ import annotations

import pytest

from app.core.delivery_resolution import (
    DeliveryEvidenceSource,
    DeliveryNotDeliveredReason,
    DeliveryResolutionAction,
)
from app.models.outbound import OutboundDeliveryResolution, OutboundMessage
from app.services.outbound_delivery_resolution import (
    InvalidDeliveryResolutionError,
    OutboundDeliveryResolutionService,
)


def test_resolution_persistence_has_separate_cas_and_idempotency_constraints() -> None:
    constraints = {
        constraint.name
        for constraint in OutboundDeliveryResolution.__table__.constraints
        if constraint.name
    }

    assert "resolution_version" in OutboundMessage.__table__.c
    assert "uq_outbound_delivery_resolution_version" in constraints
    assert "uq_outbound_delivery_resolution_idempotency" in constraints


def test_resolution_policy_requires_action_specific_evidence() -> None:
    service = OutboundDeliveryResolutionService()
    service._validate_evidence(
        action=DeliveryResolutionAction.CONFIRM_DELIVERED,
        provider_message_id="provider-123",
        evidence_source=DeliveryEvidenceSource.PROVIDER_CONSOLE,
        reason_code=None,
    )
    service._validate_evidence(
        action=DeliveryResolutionAction.CONFIRM_NOT_DELIVERED,
        provider_message_id=None,
        evidence_source=None,
        reason_code=DeliveryNotDeliveredReason.PROVIDER_RECORD_NOT_FOUND,
    )

    with pytest.raises(InvalidDeliveryResolutionError):
        service._validate_evidence(
            action=DeliveryResolutionAction.CONFIRM_DELIVERED,
            provider_message_id=None,
            evidence_source=DeliveryEvidenceSource.PROVIDER_API,
            reason_code=None,
        )
    with pytest.raises(InvalidDeliveryResolutionError):
        service._validate_evidence(
            action=DeliveryResolutionAction.CONFIRM_NOT_DELIVERED,
            provider_message_id="provider-123",
            evidence_source=None,
            reason_code=DeliveryNotDeliveredReason.PROVIDER_RECORD_NOT_FOUND,
        )
