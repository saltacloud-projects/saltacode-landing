from dataclasses import dataclass

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.contracts import ProblemDetails


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    title: str
    detail: str
    headers: dict[str, str] | None = None


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unavailable")


def problem_response(request: Request, error: ApiError) -> JSONResponse:
    problem = ProblemDetails(
        title=error.title,
        status=error.status_code,
        code=error.code,
        detail=error.detail,
        correlation_id=_correlation_id(request),
    )
    return JSONResponse(
        status_code=error.status_code,
        content=problem.model_dump(mode="json"),
        headers=error.headers,
        media_type="application/problem+json",
    )


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return problem_response(request, error)


async def validation_error_handler(
    request: Request, _error: RequestValidationError
) -> JSONResponse:
    return problem_response(
        request,
        ApiError(
            status_code=422,
            code="request_validation_failed",
            title="Request validation failed",
            detail="The request does not match the API contract.",
        ),
    )


async def unexpected_error_handler(request: Request, _error: Exception) -> JSONResponse:
    return problem_response(
        request,
        ApiError(
            status_code=500,
            code="internal_error",
            title="Internal server error",
            detail="The request could not be completed.",
        ),
    )
