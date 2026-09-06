"""Administration contract and secret-surface coverage for identity links."""

from fastapi import FastAPI

from app.routers.admin.identity_link_claims import router
from app.schemas.identity_link_claim import IdentityLinkClaimVerifyRequest

ROOT = "/api/admin/agents/{agent_id}/identity-link-claims"


def test_identity_link_claim_api_is_agent_scoped_authenticated_and_idempotent() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schema = app.openapi()
    expected = {
        (f"{ROOT}/", "get"),
        (f"{ROOT}/", "post"),
        (f"{ROOT}/{{claim_id}}", "get"),
        (f"{ROOT}/{{claim_id}}/verifications", "post"),
        (f"{ROOT}/{{claim_id}}/rejections", "post"),
        (f"{ROOT}/{{claim_id}}/revocations", "post"),
        (f"{ROOT}/{{claim_id}}/expirations", "post"),
    }

    for path, method in expected:
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"HTTPBearer": []}]
        agent_parameter = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == "agent_id" and parameter["in"] == "path"
        )
        assert agent_parameter["required"] is True

    for path, method in expected:
        if method != "post":
            continue
        header = next(
            parameter
            for parameter in schema["paths"][path][method]["parameters"]
            if parameter["name"] == "Idempotency-Key"
        )
        assert header["required"] is True


def test_identity_link_public_contract_never_exposes_proof_hashes_or_subjects() -> None:
    app = FastAPI()
    app.include_router(router, prefix=ROOT)
    schemas = app.openapi()["components"]["schemas"]
    claim_properties = schemas["IdentityLinkClaimOut"]["properties"]
    mutation_properties = schemas["IdentityLinkClaimMutationOut"]["properties"]

    assert "proof_token_hash" not in claim_properties
    assert "issue_command_hash" not in claim_properties
    assert "external_subject" not in claim_properties
    assert "proof_token" in mutation_properties


def test_opaque_verification_token_is_redacted_from_model_repr() -> None:
    token = "opaque-proof-token-that-is-at-least-forty-characters-long"
    request = IdentityLinkClaimVerifyRequest(
        expected_version=0,
        proof_token=token,
    )

    assert token not in repr(request)
    assert request.proof_token.get_secret_value() == token
