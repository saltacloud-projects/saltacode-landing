"""Modelos ORM del microservicio FastAPI."""

# noqa: F401 — imports necesarios para que SQLAlchemy / Alembic detecte los modelos
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_profile import AgentProfile
from app.models.agent_resource_binding import (
    AgentAuthorizedUserArea,
    AgentAuthorizedUserBinding,
    AgentKnowledgeBlockBinding,
    AgentOrganizationAreaBinding,
    AgentSourceBinding,
    AgentToolBinding,
)
from app.models.agent_runtime import (
    AgentRuntimeConfig,
    ChannelAgentRoute,
    ChannelConnection,
    ProviderConnection,
)
from app.models.audit_log import AuditLog
from app.models.authorized_user import AuthorizedUser
from app.models.conversation_message import ConversationMessage
from app.models.integration_source import IntegrationSource
from app.models.knowledge_block import KnowledgeBlock
from app.models.message_status import MessageStatus
from app.models.platform import (
    ChannelIdentity,
    ChatConversation,
    ChatExecution,
    ChatMessage,
    Principal,
)
from app.models.rag import (
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
from app.models.tool_config import ToolConfig
from app.models.whatsapp_inbox import WhatsAppInboundJob
