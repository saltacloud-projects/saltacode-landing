"""Administration contracts for agent-scoped identity link claims."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

IdentityLinkClaimStatus = Literal[
    "pending",
    "verified",
    "rejected",
    "revoked",
    "expired",
]


class IdentityLinkClaimCreateRequest(BaseModel):
    source_identity_id: uuid.UUID
    target_identity_id: uuid.UUID
    proof_method: Literal["opaque_token"] = "opaque_token"
    proof_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    evidence_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$",
    )


class IdentityLinkClaimCommandRequest(BaseModel):
    expected_version: int = Field(ge=0)


class IdentityLinkClaimVerifyRequest(IdentityLinkClaimCommandRequest):
    proof_token: SecretStr = Field(min_length=40, max_length=256)


class IdentityLinkClaimOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    source_identity_id: uuid.UUID
    source_principal_id: uuid.UUID
    source_channel: str
    target_identity_id: uuid.UUID
    target_principal_id: uuid.UUID
    target_channel: str
    status: IdentityLinkClaimStatus
    proof_method: str
    proof_expires_at: datetime
    proof_consumed_at: datetime | None
    evidence_sha256: str | None
    evidence_reference: str | None
    created_by_admin_id: uuid.UUID
    verified_by_admin_id: uuid.UUID | None
    verified_at: datetime | None
    rejected_at: datetime | None
    revoked_at: datetime | None
    expired_at: datetime | None
    control_version: int
    created_at: datetime
    updated_at: datetime


class IdentityLinkClaimMutationOut(BaseModel):
    claim: IdentityLinkClaimOut
    proof_token: str | None = None
    applied: bool
