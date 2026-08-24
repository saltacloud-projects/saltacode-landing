"""HTTP dependency resolution and internal service authentication."""

from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from saltacode_agent.application.ports import AgentRuntime, ReadinessProbe
from saltacode_agent.config import Settings


@dataclass(frozen=True, slots=True)
class Services:
    settings: Settings
    runtime: AgentRuntime
    readiness: ReadinessProbe


def get_services(request: Request) -> Services:
    return request.app.state.services


_bearer = HTTPBearer(auto_error=False)
ServicesDependency = Annotated[Services, Depends(get_services)]
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


async def require_internal_access(
    credentials: BearerCredentials,
    services: ServicesDependency,
) -> None:
    expected = services.settings.resolved_internal_token.get_secret_value()
    supplied = credentials.credentials if credentials is not None else ""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="internal authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="internal authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
