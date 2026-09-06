"""Provider-neutral vocabulary for resolving uncertain deliveries."""

from enum import StrEnum


class DeliveryResolutionAction(StrEnum):
    CONFIRM_DELIVERED = "confirm_delivered"
    CONFIRM_NOT_DELIVERED = "confirm_not_delivered"


class DeliveryEvidenceSource(StrEnum):
    PROVIDER_API = "provider_api"
    PROVIDER_CONSOLE = "provider_console"


class DeliveryNotDeliveredReason(StrEnum):
    PROVIDER_CONFIRMED_NOT_DELIVERED = "provider_confirmed_not_delivered"
    PROVIDER_RECORD_NOT_FOUND = "provider_record_not_found"
    OPERATOR_VERIFIED_NOT_DELIVERED = "operator_verified_not_delivered"
