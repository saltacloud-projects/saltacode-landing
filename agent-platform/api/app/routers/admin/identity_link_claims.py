"""Agent-scoped administration API for verified identity-link evidence."""

from __future__ import annotations

import uuid
from typing import Awaitable, Callable, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.routers.admin.auth import require_agent_permission
from app.schemas.identity_link_claim import (
    IdentityLinkClaimCommandRequest,
    IdentityLinkClaimCreateRequest,
    IdentityLinkClaimMutationOut,
    IdentityLinkClaimOut,
    IdentityLinkClaimStatus,
    IdentityLinkClaimVerifyRequest,
)
from app.services.admin_rbac import AdminPermission
from app.services.identity_link_claims import (
    IdentityLinkClaimConflictError,
    IdentityLinkClaimIdempotencyError,
    IdentityLinkClaimNotFoundError,
    IdentityLinkClaimResult,
    IdentityLinkClaimValidationError,
    IdentityLinkClaimVersionConflictError,
    IdentityLinkClaimView,
    IdentityProofVerificationError,
    identity_link_claim_service,
)

router = APIRouter(
    tags=["admin-identity-link-claims"],
    dependencies=[
        Depends(require_agent_permission(AdminPermission.CONVERSATIONS_READ))
    ],
)


@router.get("/", response_model=list[IdentityLinkClaimOut])
async def list_identity_link_claims(
    agent_id: uuid.UUID,
    status_filter: IdentityLinkClaimStatus | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[IdentityLinkClaimOut]:
    try:
        views = await identity_link_claim_service.list_claims(
            db,
            agent_id=agent_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except IdentityLinkClaimValidationError as exc:
        _raise_identity_link_error(exc)
    return [_out(view) for view in views]


@router.get("/{claim_id}", response_model=IdentityLinkClaimOut)
async def get_identity_link_claim(
    agent_id: uuid.UUID,
    claim_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> IdentityLinkClaimOut:
    try:
        view = await identity_link_claim_service.get_claim(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
        )
    except IdentityLinkClaimNotFoundError as exc:
        _raise_identity_link_error(exc)
    return _out(view)


@router.post(
    "/",
    response_model=IdentityLinkClaimMutationOut,
    status_code=status.HTTP_201_CREATED,
)
async def issue_identity_link_claim(
    agent_id: uuid.UUID,
    payload: IdentityLinkClaimCreateRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> IdentityLinkClaimMutationOut:
    try:
        result = await identity_link_claim_service.issue(
            db,
            agent_id=agent_id,
            source_identity_id=payload.source_identity_id,
            target_identity_id=payload.target_identity_id,
            actor_admin_id=admin.id,
            proof_method=payload.proof_method,
            proof_ttl_seconds=payload.proof_ttl_seconds,
            evidence_sha256=payload.evidence_sha256,
            evidence_reference=payload.evidence_reference,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_identity_link_error(exc)
    return _mutation_out(result)


@router.post(
    "/{claim_id}/verifications",
    response_model=IdentityLinkClaimMutationOut,
)
async def verify_identity_link_claim(
    agent_id: uuid.UUID,
    claim_id: uuid.UUID,
    payload: IdentityLinkClaimVerifyRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> IdentityLinkClaimMutationOut:
    try:
        result = await identity_link_claim_service.verify(
            db,
            agent_id=agent_id,
            claim_id=claim_id,
            actor_admin_id=admin.id,
            proof_token=payload.proof_token.get_secret_value(),
            expected_version=payload.expected_version,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise_identity_link_error(exc)
    return _mutation_out(result)


@router.post(
    "/{claim_id}/rejections",
    response_model=IdentityLinkClaimMutationOut,
)
async def reject_identity_link_claim(
    agent_id: uuid.UUID,
    claim_id: uuid.UUID,
    payload: IdentityLinkClaimCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> IdentityLinkClaimMutationOut:
    return await _run_transition(
        identity_link_claim_service.reject,
        db=db,
        agent_id=agent_id,
        claim_id=claim_id,
        actor_admin_id=admin.id,
        expected_version=payload.expected_version,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{claim_id}/revocations",
    response_model=IdentityLinkClaimMutationOut,
)
async def revoke_identity_link_claim(
    agent_id: uuid.UUID,
    claim_id: uuid.UUID,
    payload: IdentityLinkClaimCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> IdentityLinkClaimMutationOut:
    return await _run_transition(
        identity_link_claim_service.revoke,
        db=db,
        agent_id=agent_id,
        claim_id=claim_id,
        actor_admin_id=admin.id,
        expected_version=payload.expected_version,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{claim_id}/expirations",
    response_model=IdentityLinkClaimMutationOut,
)
async def expire_identity_link_claim(
    agent_id: uuid.UUID,
    claim_id: uuid.UUID,
    payload: IdentityLinkClaimCommandRequest,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=220,
    ),
    admin: AdminUser = Depends(
        require_agent_permission(AdminPermission.CONVERSATIONS_MANAGE)
    ),
    db: AsyncSession = Depends(get_db),
) -> IdentityLinkClaimMutationOut:
    return await _run_transition(
        identity_link_claim_service.expire,
        db=db,
        agent_id=agent_id,
        claim_id=claim_id,
        actor_admin_id=admin.id,
        expected_version=payload.expected_version,
        idempotency_key=idempotency_key,
    )


async def _run_transition(
    transition: Callable[..., Awaitable[IdentityLinkClaimResult]],
    **kwargs,
) -> IdentityLinkClaimMutationOut:
    try:
        result = await transition(**kwargs)
    except Exception as exc:
        _raise_identity_link_error(exc)
    return _mutation_out(result)


def _mutation_out(result: IdentityLinkClaimResult) -> IdentityLinkClaimMutationOut:
    return IdentityLinkClaimMutationOut(
        claim=_out(result.view),
        proof_token=result.proof_token,
        applied=result.applied,
    )


def _out(view: IdentityLinkClaimView) -> IdentityLinkClaimOut:
    claim = view.claim
    return IdentityLinkClaimOut(
        id=claim.id,
        agent_id=claim.agent_id,
        source_identity_id=claim.source_identity_id,
        source_principal_id=claim.source_principal_id,
        source_channel=view.source_identity.channel,
        target_identity_id=claim.target_identity_id,
        target_principal_id=claim.target_principal_id,
        target_channel=view.target_identity.channel,
        status=claim.status,
        proof_method=claim.proof_method,
        proof_expires_at=claim.proof_expires_at,
        proof_consumed_at=claim.proof_consumed_at,
        evidence_sha256=claim.evidence_sha256,
        evidence_reference=claim.evidence_reference,
        created_by_admin_id=claim.created_by_admin_id,
        verified_by_admin_id=claim.verified_by_admin_id,
        verified_at=claim.verified_at,
        rejected_at=claim.rejected_at,
        revoked_at=claim.revoked_at,
        expired_at=claim.expired_at,
        control_version=claim.control_version,
        created_at=claim.created_at,
        updated_at=claim.updated_at,
    )


def _raise_identity_link_error(exc: Exception) -> NoReturn:
    if isinstance(exc, IdentityLinkClaimNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity-link claim not found",
        ) from exc
    if isinstance(
        exc,
        (
            IdentityLinkClaimConflictError,
            IdentityLinkClaimIdempotencyError,
            IdentityLinkClaimVersionConflictError,
            IdentityProofVerificationError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if isinstance(exc, IdentityLinkClaimValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    raise exc
