"""Authentication dependencies for internal and administration APIs."""

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# Los clientes deben enviar este header en cada request protegido
# Header: X-API-Key: <valor de FASTAPI_API_KEY en .env>
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)


async def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    """
    Dependency que valida la API Key.
    Uso en routers:
        @router.get("/endpoint", dependencies=[Depends(require_api_key)])
    """
    if not api_key or not hmac.compare_digest(api_key, settings.fastapi_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key inválida o ausente",
        )
    return api_key


async def require_internal_bearer(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, settings.fastapi_api_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal credentials",
        )
    return credentials.credentials
