from hashlib import sha256
from ipaddress import ip_address

from fastapi import Request

from app.config import Settings
from app.errors import ApiError


def enforce_allowed_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        return
    if origin.rstrip("/") not in settings.allowed_origin_set:
        raise ApiError(
            status_code=403,
            code="origin_not_allowed",
            title="Origin not allowed",
            detail="The request origin is not allowed.",
        )


def rate_limit_client_identity(request: Request) -> str:
    cloudflare_values = request.headers.getlist("CF-Connecting-IP")
    if cloudflare_values:
        try:
            if len(cloudflare_values) != 1:
                raise ValueError("multiple client address headers")
            address = ip_address(cloudflare_values[0].strip())
            if getattr(address, "scope_id", None) is not None:
                raise ValueError("scoped client address")
            return str(address)
        except ValueError as error:
            raise ApiError(
                status_code=400,
                code="invalid_client_ip",
                title="Invalid client address",
                detail="The client address header is malformed.",
            ) from error
    return request.client.host if request.client is not None else "unknown"


def client_rate_limit_key(identity: str) -> str:
    return f"chat:{sha256(identity.encode('utf-8')).hexdigest()}"
