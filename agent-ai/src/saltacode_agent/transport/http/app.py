"""FastAPI application factory for the private agent service."""

from typing import cast

from fastapi import FastAPI

from saltacode_agent import __version__
from saltacode_agent.adapters.unavailable import UnavailableAgentRuntime
from saltacode_agent.application.ports import AgentRuntime, ReadinessProbe
from saltacode_agent.config import Settings, get_settings
from saltacode_agent.transport.http.dependencies import Services
from saltacode_agent.transport.http.routes import router


def create_app(
    settings: Settings | None = None,
    runtime: AgentRuntime | None = None,
    readiness: ReadinessProbe | None = None,
) -> FastAPI:
    """Create a service with explicit replaceable adapters."""

    resolved_settings = settings or get_settings()
    resolved_runtime = runtime or UnavailableAgentRuntime()
    if readiness is not None:
        resolved_readiness = readiness
    elif hasattr(resolved_runtime, "check"):
        resolved_readiness = cast(ReadinessProbe, resolved_runtime)
    else:
        resolved_readiness = UnavailableAgentRuntime()

    app = FastAPI(
        title="Saltacode Agent Internal API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = Services(
        settings=resolved_settings,
        runtime=resolved_runtime,
        readiness=resolved_readiness,
    )
    app.include_router(router)
    return app
