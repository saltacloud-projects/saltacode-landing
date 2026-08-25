from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, load_settings
from app.correlation import correlation_middleware
from app.errors import (
    ApiError,
    api_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.gateway import HttpAgentGateway, UnavailableAgentGateway
from app.ports import AgentGateway, RateLimiter
from app.rate_limit import InMemoryFixedWindowRateLimiter, RedisFixedWindowRateLimiter
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router


def _build_agent_gateway(settings: Settings) -> AgentGateway:
    if settings.agent_ai_base_url is None:
        return UnavailableAgentGateway()
    return HttpAgentGateway(
        base_url=settings.agent_ai_base_url,
        connect_timeout_seconds=settings.agent_ai_connect_timeout_seconds,
        response_timeout_seconds=settings.agent_ai_response_timeout_seconds,
        internal_token=settings.resolve_agent_internal_token(),
    )


def _build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.rate_limit_backend == "memory":
        return InMemoryFixedWindowRateLimiter(
            requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    redis_url = settings.resolve_redis_url()
    if redis_url is None:
        raise ValueError("Redis rate-limit backend requires a Redis URL")
    return RedisFixedWindowRateLimiter.from_url(
        url=redis_url,
        requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        connect_timeout_seconds=settings.redis_connect_timeout_seconds,
        response_timeout_seconds=settings.redis_response_timeout_seconds,
    )


def create_app(
    settings: Settings | None = None,
    agent_gateway: AgentGateway | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        try:
            await application.state.agent_gateway.aclose()
        finally:
            await application.state.rate_limiter.aclose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="1.0.0",
        docs_url="/docs" if resolved_settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.rate_limiter = rate_limiter or _build_rate_limiter(resolved_settings)
    app.state.agent_gateway = agent_gateway or _build_agent_gateway(resolved_settings)

    app.middleware("http")(correlation_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(resolved_settings.allowed_origin_set),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Correlation-ID"],
        expose_headers=["X-Correlation-ID", "X-RateLimit-Remaining"],
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    app.include_router(health_router)
    app.include_router(chat_router)
    return app


app = create_app()
