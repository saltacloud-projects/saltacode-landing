"""FastAPI entrypoint for the multi-channel agent platform."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.core.database import engine
from app.core.logging import setup_logging

# Routers
from app.routers import health, internal
from app.routers.admin.agent_resources import router as admin_agent_resources_router
from app.routers.admin.agent_runtime import router as admin_agent_runtime_router
from app.routers.admin.audit import router as admin_audit_router
from app.routers.admin.auth import router as admin_auth_router
from app.routers.admin.config import router as admin_config_router
from app.routers.admin.conversations import router as admin_conversations_router
from app.routers.admin.documents import router as admin_documents_router
from app.routers.admin.knowledge_blocks import router as admin_kb_router
from app.routers.admin.panel_users import router as admin_panel_users_router
from app.routers.admin.profiles import router as admin_profiles_router
from app.routers.admin.promptlab import router as admin_promptlab_router
from app.routers.admin.sources import router as admin_sources_router
from app.routers.admin.tools import router as admin_tools_router
from app.routers.admin.users import router as admin_users_router
from app.routers.audit import router as audit_router
from app.routers.executions import router as executions_router
from app.routers.governance import router as governance_router
from app.routers.tools import router as tools_router
from app.routers.webhooks import router as webhooks_router

logger = logging.getLogger(__name__)

_PRODUCTION_TRUSTED_HOSTS = (
    settings.domain,
    "fastapi",
    "agent-platform",
    "localhost",
    "127.0.0.1",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()

    # Las tablas se crean/modifican exclusivamente via: alembic upgrade head
    # No usar Base.metadata.create_all — bypasea el historial de migraciones

    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
    )

    # La tool documental sólo entrega originales citados. La búsqueda RAG es
    # automática y no pasa por tool_registry. Se registra siempre para que una
    # habilitación persistida no requiera reinicio posterior.
    from app.services.tools.adapters.rag import register_rag_tools
    from app.services.tools.registry import tool_registry

    register_rag_tools(tool_registry)

    # Source-bound declarative tools are loaded from PostgreSQL. Credentials are
    # decrypted only at invocation time and never stored in runtime metadata.
    # Se registran desde la DB para quedar disponibles sin tocar código ni redeploy.
    # Protegido: si la columna aún no existe (migración pendiente), no corta el arranque.
    try:
        from app.core.database import AsyncSessionLocal as _ToolsSession
        from app.services.tools.dynamic import sync_http_api_tools

        async with _ToolsSession() as _tools_db:
            _n_http = await sync_http_api_tools(_tools_db)
        logger.info("http_api_tools_registered", extra={"count": _n_http})
    except Exception as e:
        logger.error("http_api_tools_sync_failed", extra={"error": str(e)})

    llm_mode = "openai" if settings.openai_api_key else "rules"
    wa_mode = "live" if settings.whatsapp_token else "disabled"
    logger.info(
        "app_startup_complete",
        extra={
            "classifier": llm_mode,
            "whatsapp": wa_mode,
            "tools": tool_registry.list_tools(),
        },
    )

    # Verificar estado de configuración del agente al arrancar
    from app.core.database import AsyncSessionLocal as _SessionLocal
    from app.services.configuration import configuration_service

    try:
        async with _SessionLocal() as _db:
            config_status = await configuration_service.check(_db)
            if config_status.is_ready:
                logger.info("agent_configuration_ready")
            else:
                error_issues = [
                    i.message for i in config_status.issues if i.level == "error"
                ]
                warn_issues = [
                    i.message for i in config_status.issues if i.level == "warning"
                ]
                logger.warning(
                    "agent_configuration_not_ready",
                    extra={"errors": error_issues, "warnings": warn_issues},
                )
    except Exception as e:
        logger.error("agent_configuration_check_failed", extra={"error": str(e)})

    from app.services.retention import (
        purge_expired_conversations,
        run_retention_sweeper,
    )

    try:
        async with _SessionLocal() as _db:
            deleted_count = await purge_expired_conversations(_db)
        if deleted_count:
            logger.info(
                "expired_conversations_deleted",
                extra={"count": deleted_count},
            )
    except Exception:
        logger.exception("initial_conversation_retention_sweep_failed")

    retention_task = asyncio.create_task(
        run_retention_sweeper(
            _SessionLocal,
            settings.retention_sweep_interval_seconds,
        ),
        name="conversation-retention-sweeper",
    )

    yield

    retention_task.cancel()
    with suppress(asyncio.CancelledError):
        await retention_task

    from app.services.http_executor import restricted_http_executor

    await restricted_http_executor.aclose()
    await app.state.redis.aclose()
    await engine.dispose()
    logger.info("app_shutdown_complete")


_docs_url = "/docs" if settings.fastapi_env != "production" else None
_redoc_url = "/redoc" if settings.fastapi_env != "production" else None

app = FastAPI(
    title="Agent Platform API",
    description="Private multi-channel agent and integration platform",
    version=settings.app_version,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — permite al frontend admin hacer requests al backend
# ---------------------------------------------------------------------------
_cors_origins = [settings.admin_frontend_url]
if settings.fastapi_env != "production":
    _cors_origins.append("http://localhost:5173")  # Vite dev server

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.fastapi_env == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(_PRODUCTION_TRUSTED_HOSTS),
    )

# ---------------------------------------------------------------------------
# Routers de canal de entrada (sin autenticación — Meta verifica por token)
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(internal.router, prefix="/internal")
app.include_router(executions_router)
app.include_router(webhooks_router, prefix="/webhooks")
app.include_router(
    webhooks_router, prefix="/webhook"
)  # compatibilidad con URL configurada en Meta

# ---------------------------------------------------------------------------
# Routers internos (requieren X-API-Key)
# ---------------------------------------------------------------------------
app.include_router(governance_router, prefix="/internal/governance")
app.include_router(audit_router, prefix="/internal/audit")
app.include_router(tools_router, prefix="/internal/tools")

# ---------------------------------------------------------------------------
# Routers admin panel (requieren JWT)
# ---------------------------------------------------------------------------
app.include_router(admin_auth_router, prefix="/api/admin/auth")
app.include_router(admin_profiles_router, prefix="/api/admin/profiles")
app.include_router(admin_kb_router, prefix="/api/admin/knowledge-blocks")
app.include_router(admin_tools_router, prefix="/api/admin/tools")
app.include_router(admin_users_router, prefix="/api/admin/users")
app.include_router(admin_audit_router, prefix="/api/admin/audit")
app.include_router(admin_conversations_router, prefix="/api/admin/conversations")
app.include_router(admin_config_router, prefix="/api/admin/config")
app.include_router(admin_promptlab_router, prefix="/api/admin/promptlab")
app.include_router(admin_documents_router, prefix="/api/admin/documents")
app.include_router(admin_panel_users_router, prefix="/api/admin/panel-users")
app.include_router(admin_sources_router, prefix="/api/admin/sources")
app.include_router(admin_agent_resources_router, prefix="/api/admin/agents")
app.include_router(admin_agent_runtime_router, prefix="/api/admin")
