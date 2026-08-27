"""
Agent Platform — Alembic env.py
Configuración de migraciones con SQLAlchemy async (asyncpg).
"""
import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Asegurar que /app está en el path para importar app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.core.database import Base  # noqa: E402

# Importar TODOS los modelos para que Alembic los detecte en --autogenerate
from app.models.base import TimestampedModel  # noqa: F401
from app.models.authorized_user import AuthorizedUser  # noqa: F401
from app.models.usage_record import UsageRecord  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.tool_config import ToolConfig  # noqa: F401
from app.models.conversation_message import ConversationMessage  # noqa: F401
from app.models.agent_profile import AgentProfile  # noqa: F401
from app.models.message_status import MessageStatus  # noqa: F401
from app.models.integration_source import IntegrationSource  # noqa: F401
from app.models.platform import (  # noqa: F401
    ChannelIdentity,
    ChatConversation,
    ChatExecution,
    ChatMessage,
    Principal,
)
from app.models.knowledge_block import KnowledgeBlock  # noqa: F401
from app.models.admin_user import AdminUser  # noqa: F401
from app.models.admin_role import AdminRole  # noqa: F401
from app.models.rag import (  # noqa: F401
    AuthorizedUserArea,
    Document,
    DocumentBlob,
    DocumentChunk,
    DocumentEvent,
    DocumentFolder,
    DocumentIngestionJob,
    DocumentVersion,
    OrganizationArea,
    RagSettings,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata de los modelos — usada por --autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Modo offline: genera SQL sin conexión a la DB.
    Útil para generar scripts de migración para aplicar manualmente.
    """
    context.configure(
        url=settings.postgres_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Modo online con engine async (asyncpg)."""
    configuration = config.get_section(config.config_ini_section, {})
    # Sobreescribir la URL de alembic.ini con la del settings (que usa asyncpg)
    configuration["sqlalchemy.url"] = settings.postgres_dsn

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # Sin pool: cada migración abre/cierra conexión
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
