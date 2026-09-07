"""Shared query validation for global and agent-scoped Inbox message filters."""

from fastapi import HTTPException, Query
from pydantic import ValidationError

from app.schemas.operator_inbox import InboxMessageFilters

_RFC3339 = r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"


def inbox_message_filters(
    last_message_from: str | None = Query(
        default=None, pattern=_RFC3339, max_length=64
    ),
    last_message_before: str | None = Query(
        default=None, pattern=_RFC3339, max_length=64
    ),
    unread_only: bool = False,
    search: str | None = Query(default=None, max_length=120),
) -> InboxMessageFilters:
    try:
        return InboxMessageFilters(
            last_message_from=last_message_from,
            last_message_before=last_message_before,
            unread_only=unread_only,
            search=search,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_context=False, include_input=False),
        ) from exc
