import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

CORRELATION_HEADER = "X-Correlation-ID"
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def correlation_id_from_request(request: Request) -> str:
    candidate = request.headers.get(CORRELATION_HEADER, "")
    if _SAFE_CORRELATION_ID.fullmatch(candidate):
        return candidate
    return str(uuid4())


async def correlation_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    correlation_id = correlation_id_from_request(request)
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = correlation_id
    return response
