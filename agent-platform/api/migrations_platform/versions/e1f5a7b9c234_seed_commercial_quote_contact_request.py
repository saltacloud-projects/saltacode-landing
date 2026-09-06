"""Seed the native quote contact-request capability.

Revision ID: e1f5a7b9c234
Revises: d0e4f6a8b123
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f5a7b9c234"
down_revision: str | None = "d0e4f6a8b123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TOOL_ID = uuid.UUID("2a0a5cc2-bf7f-4f73-a2eb-11dc7e22b075")
_TOOL_NAME = "commercial_quote_contact_request"


def upgrade() -> None:
    tool_registry = _tool_registry_table()
    op.execute(
        tool_registry.insert().values(
            id=_TOOL_ID,
            tool_name=_TOOL_NAME,
            description=(
                "Request explicit contact details and consent before preparing "
                "quote delivery. This capability never captures contact data itself."
            ),
            source_system="platform",
            source_id=None,
            is_enabled=True,
            auth_required=True,
            params_schema={
                "title": {
                    "type": "string",
                    "description": "Short title for the requested quote.",
                    "required": True,
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "Brief business need summary without personal or contact data."
                    ),
                    "required": True,
                },
                "preferred_delivery_channel": {
                    "type": "string",
                    "description": "Requested quote delivery channel.",
                    "enum": ["email", "whatsapp"],
                    "required": True,
                },
            },
            timeout_seconds=10,
            cost_category="low",
            handler_path=(
                "app.services.tools.adapters.commercial_quote_contact_request."
                "CommercialQuoteContactRequestTool"
            ),
            result_type="json",
            handler_kind="native",
            http_config=None,
            allowed_channels=["web", "whatsapp"],
            risk_level="idempotent",
            requires_confirmation=False,
        )
    )


def downgrade() -> None:
    tool_registry = _tool_registry_table()
    op.execute(
        tool_registry.delete().where(
            tool_registry.c.id == _TOOL_ID,
            tool_registry.c.tool_name == _TOOL_NAME,
        )
    )


def _tool_registry_table() -> sa.Table:
    return sa.table(
        "tool_registry",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("tool_name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("source_system", sa.String()),
        sa.column("source_id", postgresql.UUID(as_uuid=True)),
        sa.column("is_enabled", sa.Boolean()),
        sa.column("auth_required", sa.Boolean()),
        sa.column("params_schema", postgresql.JSONB()),
        sa.column("timeout_seconds", sa.Integer()),
        sa.column("cost_category", sa.String()),
        sa.column("handler_path", sa.String()),
        sa.column("result_type", sa.String()),
        sa.column("handler_kind", sa.String()),
        sa.column("http_config", postgresql.JSONB()),
        sa.column("allowed_channels", postgresql.JSONB()),
        sa.column("risk_level", sa.String()),
        sa.column("requires_confirmation", sa.Boolean()),
    )
