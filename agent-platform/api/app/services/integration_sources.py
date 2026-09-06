"""Application service for integration source lifecycle."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration_source import IntegrationSource
from app.schemas.integrations import IntegrationSourceCreate, IntegrationSourceUpdate
from app.services.credentials import credential_cipher


class IntegrationSourceService:
    async def list(self, db: AsyncSession) -> list[IntegrationSource]:
        rows = await db.execute(
            select(IntegrationSource).order_by(IntegrationSource.name)
        )
        return list(rows.scalars().all())

    async def get(
        self, db: AsyncSession, source_id: uuid.UUID
    ) -> IntegrationSource | None:
        return await db.get(IntegrationSource, source_id)

    async def create(
        self,
        db: AsyncSession,
        data: IntegrationSourceCreate,
        *,
        actor: str,
    ) -> IntegrationSource:
        existing = (
            await db.execute(
                select(IntegrationSource.id).where(IntegrationSource.slug == data.slug)
            )
        ).scalar_one_or_none()
        if existing:
            raise ValueError("an integration source with this slug already exists")
        payload = data.model_dump(exclude={"credentials"})
        source = IntegrationSource(**payload, created_by=actor)
        if data.credentials is not None:
            source.encrypted_credentials = credential_cipher.encrypt(data.credentials)
        db.add(source)
        await db.flush()
        return source

    async def update(
        self,
        db: AsyncSession,
        source: IntegrationSource,
        data: IntegrationSourceUpdate,
    ) -> IntegrationSource:
        requested = data.model_dump(
            exclude_none=True, exclude={"credentials", "clear_credentials"}
        )
        candidate = IntegrationSourceCreate(
            name=requested.get("name", source.name),
            slug=source.slug,
            source_type=source.source_type,
            base_url=requested.get("base_url", source.base_url),
            allowed_hosts=requested.get(
                "allowed_hosts", list(source.allowed_hosts or [])
            ),
            auth_type=requested.get("auth_type", source.auth_type),
            auth_config=requested.get("auth_config", dict(source.auth_config or {})),
            default_headers=requested.get(
                "default_headers", dict(source.default_headers or {})
            ),
            is_active=requested.get("is_active", source.is_active),
            is_public=requested.get("is_public", source.is_public),
            verify_tls=requested.get("verify_tls", source.verify_tls),
            allow_private_network=requested.get(
                "allow_private_network", source.allow_private_network
            ),
            timeout_seconds=requested.get("timeout_seconds", source.timeout_seconds),
            max_response_bytes=requested.get(
                "max_response_bytes", source.max_response_bytes
            ),
        )
        for field in requested:
            setattr(source, field, getattr(candidate, field))
        if data.clear_credentials:
            source.encrypted_credentials = None
        elif data.credentials is not None:
            source.encrypted_credentials = credential_cipher.encrypt(data.credentials)
        await db.flush()
        return source


integration_source_service = IntegrationSourceService()
