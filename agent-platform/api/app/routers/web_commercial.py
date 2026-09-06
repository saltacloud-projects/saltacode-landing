"""Private commercial-contact ingress consumed only by the public BFF."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_internal_bearer
from app.dependencies import get_db
from app.schemas.web_commercial import (
    WebCommercialContactAccepted,
    WebCommercialContactRequest,
)
from app.services.commercial.consents import (
    ConsentIdempotencyConflictError,
    ConsentServiceError,
)
from app.services.commercial.contact_crypto import (
    ContactCryptoUnavailable,
    InvalidContactPointValue,
)
from app.services.commercial.contacts import (
    ContactSemanticConflictError,
    ContactServiceError,
)
from app.services.commercial.handoffs import (
    CommercialHandoffConsentRequiredError,
    CommercialHandoffContactEvidenceError,
    CommercialHandoffRouteRequiredError,
)
from app.services.commercial.opportunities import (
    InvalidOpportunityCommandError,
    OpportunityIdempotencyConflictError,
)
from app.services.web_commercial import (
    WebCommercialRequestConflictError,
    WebCommercialRouteUnavailableError,
    WebCommercialSessionBlockedError,
    WebCommercialSessionNotFoundError,
    web_commercial_service,
)

router = APIRouter(
    prefix="/internal/v2/web",
    tags=["web-commercial"],
    dependencies=[Depends(require_internal_bearer)],
)


@router.post(
    "/commercial-contact",
    response_model=WebCommercialContactAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def capture_commercial_contact(
    request: WebCommercialContactRequest,
    db: AsyncSession = Depends(get_db),
) -> WebCommercialContactAccepted:
    try:
        response = await web_commercial_service.capture(db, request)
        await db.commit()
        return response
    except Exception as exc:
        _raise_web_commercial_error(exc)


def _raise_web_commercial_error(exc: Exception) -> NoReturn:
    if isinstance(exc, WebCommercialSessionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Web chat session was not found.",
        ) from exc
    if isinstance(
        exc,
        (
            ConsentIdempotencyConflictError,
            OpportunityIdempotencyConflictError,
            WebCommercialRequestConflictError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client request id conflicts with stored commercial input.",
        ) from exc
    if isinstance(exc, WebCommercialSessionBlockedError):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Web chat session is not available.",
        ) from exc
    if isinstance(
        exc,
        (
            ContactSemanticConflictError,
            ContactServiceError,
            ConsentServiceError,
            CommercialHandoffConsentRequiredError,
            CommercialHandoffContactEvidenceError,
            InvalidContactPointValue,
            InvalidOpportunityCommandError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid commercial contact request.",
        ) from exc
    if isinstance(
        exc,
        (
            ContactCryptoUnavailable,
            CommercialHandoffRouteRequiredError,
            WebCommercialRouteUnavailableError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Commercial contact capture is unavailable.",
        ) from exc
    raise exc
