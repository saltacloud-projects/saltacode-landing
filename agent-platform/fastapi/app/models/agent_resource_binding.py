"""Explicit ownership bindings between agents and reusable platform resources."""

import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class AgentSourceBinding(TimestampedModel):
    __tablename__ = "agent_source_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "source_id", name="uq_agent_source_binding"),
        Index("ix_agent_source_bindings_agent_id", "agent_id"),
        Index("ix_agent_source_bindings_source_id", "source_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integration_sources.id", ondelete="CASCADE"),
        nullable=False,
    )


class AgentToolBinding(TimestampedModel):
    __tablename__ = "agent_tool_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "tool_id", name="uq_agent_tool_binding"),
        Index("ix_agent_tool_bindings_agent_id", "agent_id"),
        Index("ix_agent_tool_bindings_tool_id", "tool_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tool_registry.id", ondelete="CASCADE"),
        nullable=False,
    )


class AgentKnowledgeBlockBinding(TimestampedModel):
    __tablename__ = "agent_knowledge_block_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "knowledge_block_id", name="uq_agent_knowledge_block_binding"
        ),
        Index("ix_agent_knowledge_block_bindings_agent_id", "agent_id"),
        Index(
            "ix_agent_knowledge_block_bindings_knowledge_block_id",
            "knowledge_block_id",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_block_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_blocks.id", ondelete="CASCADE"),
        nullable=False,
    )


class AgentOrganizationAreaBinding(TimestampedModel):
    """Assign an existing RAG area (the current document aggregate) to an agent."""

    __tablename__ = "agent_organization_area_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "area_id", name="uq_agent_organization_area_binding"
        ),
        Index("ix_agent_organization_area_bindings_agent_id", "agent_id"),
        Index("ix_agent_organization_area_bindings_area_id", "area_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    area_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_areas.id", ondelete="CASCADE"),
        nullable=False,
    )
