"""Contract coverage for private web commercial-contact capture."""

from uuid import uuid4

from fastapi import FastAPI
from pydantic import ValidationError

from app.routers.web_commercial import router
from app.schemas.web_commercial import WebCommercialContactRequest


def _payload() -> dict:
    return {
        "session_id": str(uuid4()),
        "route_key": "saltacode-landing",
        "client_request_id": str(uuid4()),
        "locale": "es-AR",
        "policy_version": "privacy-v1",
        "title": "Website quote",
        "summary": "Public company website",
        "contact_kind": "email",
        "contact_value": "lead@example.com",
        "preferred_delivery_channel": "email",
        "quote_delivery_consent": True,
        "commercial_follow_up_consent": False,
    }


def test_web_commercial_api_is_internal_authenticated_and_accepted() -> None:
    app = FastAPI()
    app.include_router(router)
    operation = app.openapi()["paths"]["/internal/v2/web/commercial-contact"]["post"]

    assert operation["security"] == [{"HTTPBearer": []}]
    assert "202" in operation["responses"]


def test_web_commercial_contract_requires_explicit_quote_consent() -> None:
    payload = _payload()
    payload["quote_delivery_consent"] = False

    try:
        WebCommercialContactRequest.model_validate(payload)
    except ValidationError as exc:
        assert "quote_delivery_consent" in str(exc)
    else:
        raise AssertionError("quote delivery consent must be affirmative")


def test_web_commercial_contract_matches_contact_to_delivery_channel() -> None:
    payload = _payload()
    payload["preferred_delivery_channel"] = "whatsapp"

    try:
        WebCommercialContactRequest.model_validate(payload)
    except ValidationError as exc:
        assert "contact kind must match" in str(exc)
    else:
        raise AssertionError("delivery channel without matching contact was accepted")


def test_web_commercial_contract_forbids_unknown_fields() -> None:
    payload = _payload()
    payload["transcript_consent"] = True

    try:
        WebCommercialContactRequest.model_validate(payload)
    except ValidationError as exc:
        assert "transcript_consent" in str(exc)
    else:
        raise AssertionError("unknown consent input was accepted")
