"""Authenticated SSE snapshots without holding a database session while idle."""

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.routers.admin.auth import require_admin
from app.schemas.operator_inbox import InboxLiveSnapshotOut
from app.services.admin_agent_access import admin_agent_access_service
from app.services.admin_rbac import AdminPermission, admin_rbac_service
from app.services.inbox_live import inbox_live_snapshot

router = APIRouter(tags=["admin-inbox-live"])
_bearer = HTTPBearer(auto_error=False)


def _event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _authorized_snapshot(
    credentials: HTTPAuthorizationCredentials | None,
) -> InboxLiveSnapshotOut:
    # Re-decode JWT and re-read persisted account/role/grants every tick.
    async with AsyncSessionLocal() as db:
        admin = await require_admin(credentials=credentials, db=db)
        if not await admin_rbac_service.has_permission(
            db, role_key=admin.role, permission=AdminPermission.CONVERSATIONS_READ
        ):
            raise HTTPException(status_code=403, detail="Inbox access revoked")
        agents = await admin_agent_access_service.list_operation_agents(
            db,
            admin_user_id=admin.id,
            role_key=admin.role,
            permission=AdminPermission.CONVERSATIONS_READ,
        )
        return await inbox_live_snapshot(db, admin_user_id=admin.id, agents=agents)


async def _stream(request: Request, credentials, initial: InboxLiveSnapshotOut):
    started = time.monotonic()
    last_event = started
    revision = initial.revision
    yield _event("inbox.snapshot", initial.model_dump(mode="json"))
    while time.monotonic() - started < settings.inbox_live_max_seconds:
        await asyncio.sleep(settings.inbox_live_poll_seconds)
        if await request.is_disconnected():
            return
        try:
            snapshot = await _authorized_snapshot(credentials)
        except HTTPException:
            yield _event("inbox.access_revoked", {})
            return
        if snapshot.revision != revision:
            yield _event("inbox.snapshot", snapshot.model_dump(mode="json"))
            revision = snapshot.revision
            last_event = time.monotonic()
        elif time.monotonic() - last_event >= settings.inbox_live_heartbeat_seconds:
            yield ": heartbeat\n\n"
            last_event = time.monotonic()


@router.get("/inbox/live")
async def stream_inbox(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> StreamingResponse:
    initial = await _authorized_snapshot(credentials)
    return StreamingResponse(
        _stream(request, credentials, initial),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
