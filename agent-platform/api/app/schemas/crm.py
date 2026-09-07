"""Authorized CRM collections with explicit command ownership and capabilities."""

from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel

from app.schemas.admin import AuditLogAdminOut
from app.schemas.channel_inbound import ChannelInboundSummaryOut
from app.schemas.commercial import OpportunitySummaryOut
from app.schemas.deliveries import DeliverySummaryOut
from app.schemas.follow_up_operations import FollowUpQueueItemOut
from app.schemas.meeting import MeetingSummaryOut
from app.schemas.operator_inbox import InboxConversationOut

CrmResource = Literal[
    "inbox",
    "opportunities",
    "meetings",
    "follow-ups",
    "deliveries",
    "inbound-jobs",
    "audit",
    "automation",
]


class CrmAgentOut(BaseModel):
    id: UUID
    name: str
    is_active: bool
    capabilities: list[str]


class CrmOwnershipOut(BaseModel):
    owner_agent_id: UUID
    owner_agent_name: str
    capabilities: list[str]


class CrmInboxOut(InboxConversationOut, CrmOwnershipOut):
    """Routing ownership is separate from the currently acting agent."""


class CrmOpportunityOut(OpportunitySummaryOut, CrmOwnershipOut):
    """The assigned commercial agent owns opportunity commands."""


class CrmMeetingOut(MeetingSummaryOut, CrmOwnershipOut):
    """Meeting commands follow current opportunity ownership."""


class CrmFollowUpOut(FollowUpQueueItemOut, CrmOwnershipOut):
    """Owner metadata is current; assigned_agent_id remains the task snapshot."""


class CrmDeliveryOut(DeliverySummaryOut, CrmOwnershipOut):
    """Delivery commands retain the immutable outbound agent scope."""


class CrmInboundOut(ChannelInboundSummaryOut, CrmOwnershipOut):
    """Inbound review uses the job's resolved routing owner."""


class CrmAuditOut(AuditLogAdminOut, CrmOwnershipOut):
    """Only explicitly attributed, authorized audit rows enter this view."""


Item = TypeVar("Item", bound=BaseModel)


class CrmPageOut(BaseModel, Generic[Item]):
    items: list[Item]
    total: int
    limit: int
    offset: int
