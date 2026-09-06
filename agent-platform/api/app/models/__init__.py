"""Modelos ORM del microservicio FastAPI."""

# noqa: F401 — imports necesarios para que SQLAlchemy / Alembic detecte los modelos
from app.models.admin_agent_grant import AdminAgentGrant
from app.models.admin_role import AdminRole
from app.models.admin_user import AdminUser
from app.models.agent_handoff_route import (
    AgentHandoffRoute,
    AgentHandoffRouteReceipt,
)
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
from app.models.channel_inbound import ChannelInboundEvent, ChannelInboundJob
from app.models.commercial_automation_policy import CommercialAutomationPolicy
from app.models.contact import ConsentRecord, Contact, ContactPoint
from app.models.conversation_automation_assignment import (
    ConversationAutomationAssignmentEvent,
)
from app.models.conversation_control import ConversationControlEvent
from app.models.conversation_event import ConversationEvent
from app.models.conversation_message import ConversationMessage
from app.models.follow_up import FollowUpTask, FollowUpTaskEvent
from app.models.identity_link_claim import IdentityLinkClaim, IdentityLinkClaimEvent
from app.models.integration_source import IntegrationSource
from app.models.knowledge_block import KnowledgeBlock
from app.models.meeting import Meeting, MeetingEvent, MeetingSlot
from app.models.message_status import MessageStatus
from app.models.opportunity import (
    Opportunity,
    OpportunityConversation,
    OpportunityOwnershipEvent,
    OpportunityStageEvent,
)
from app.models.outbound import (
    OutboundAttempt,
    OutboundDeliveryEvent,
    OutboundDeliveryResolution,
    OutboundMessage,
)
from app.models.platform import (
    ChannelIdentity,
    ChatConversation,
    ChatExecution,
    ChatMessage,
    Principal,
)
from app.models.quote import QuoteRequest, QuoteVersion
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
