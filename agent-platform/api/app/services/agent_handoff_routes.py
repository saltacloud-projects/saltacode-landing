"""Agent-scoped deterministic handoff-route configuration."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_handoff_route import (
    AgentHandoffRoute,
    AgentHandoffRouteReceipt,
)
from app.models.agent_profile import AgentProfile


class AgentHandoffTrigger(StrEnum):
    QUOTE_REQUESTED = "quote_requested"
    MANUAL_ESCALATION = "manual_escalation"


class AgentHandoffRouteError(Exception):
    """Base failure for deterministic handoff-route policy."""


class AgentHandoffRouteNotFoundError(AgentHandoffRouteError):
    """The route is absent from the requested source-agent scope."""


class AgentHandoffRouteValidationError(AgentHandoffRouteError):
    """The route violates a domain invariant."""


class AgentHandoffRouteConflictError(AgentHandoffRouteError):
    """The requested command conflicts with durable state."""


class AgentHandoffRouteVersionConflictError(AgentHandoffRouteConflictError):
    """The caller acted on an obsolete route version."""


class AgentHandoffRouteIdempotencyError(AgentHandoffRouteConflictError):
    """An idempotency key was reused for another command."""


@dataclass(frozen=True, slots=True)
class AgentHandoffRouteResult:
    route: AgentHandoffRoute
    applied: bool


class AgentHandoffRouteService:
    """Configure routes without executing handoffs or changing ownership."""

    async def list_routes(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
    ) -> list[AgentHandoffRoute]:
        return list(
            (
                await db.execute(
                    select(AgentHandoffRoute)
                    .where(AgentHandoffRoute.source_agent_id == source_agent_id)
                    .order_by(AgentHandoffRoute.trigger, AgentHandoffRoute.id)
                )
            )
            .scalars()
            .all()
        )

    async def get_route(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        route_id: uuid.UUID,
    ) -> AgentHandoffRoute:
        return await self._load_route(
            db,
            source_agent_id=source_agent_id,
            route_id=route_id,
        )

    async def create_route(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
        trigger: AgentHandoffTrigger | str,
        is_active: bool,
        actor_admin_id: uuid.UUID,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> AgentHandoffRouteResult:
        key = self._required_key(idempotency_key)
        normalized_trigger = self._trigger(trigger)
        event_time = self._aware_utc(occurred_at or datetime.now(UTC))
        command_hash = self._command_hash(
            {
                "actor_admin_id": str(actor_admin_id),
                "command_type": "created",
                "is_active": is_active,
                "source_agent_id": str(source_agent_id),
                "target_agent_id": str(target_agent_id),
                "trigger": normalized_trigger.value,
            }
        )
        duplicate = await self._receipt_by_key(
            db,
            source_agent_id=source_agent_id,
            idempotency_key=key,
        )
        if duplicate is not None:
            self._assert_command_hash(duplicate.command_hash, command_hash)
            route = await self._load_route(
                db,
                source_agent_id=source_agent_id,
                route_id=duplicate.route_id,
            )
            return AgentHandoffRouteResult(route=route, applied=False)

        await self._validate_agents(
            db,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
        )
        route_id = uuid.uuid5(
            source_agent_id,
            f"agent-handoff-route:{normalized_trigger.value}",
        )
        inserted_id = (
            await db.execute(
                insert(AgentHandoffRoute)
                .values(
                    id=route_id,
                    source_agent_id=source_agent_id,
                    target_agent_id=target_agent_id,
                    trigger=normalized_trigger.value,
                    is_active=is_active,
                    control_version=0,
                    created_by_admin_id=actor_admin_id,
                    updated_by_admin_id=actor_admin_id,
                    created_at=event_time,
                    updated_at=event_time,
                )
                .on_conflict_do_nothing(
                    constraint="uq_agent_handoff_route_source_trigger"
                )
                .returning(AgentHandoffRoute.id)
            )
        ).scalar_one_or_none()
        if inserted_id is None:
            duplicate = await self._receipt_by_key(
                db,
                source_agent_id=source_agent_id,
                idempotency_key=key,
            )
            if duplicate is not None:
                self._assert_command_hash(duplicate.command_hash, command_hash)
                route = await self._load_route(
                    db,
                    source_agent_id=source_agent_id,
                    route_id=duplicate.route_id,
                )
                return AgentHandoffRouteResult(route=route, applied=False)
            raise AgentHandoffRouteConflictError(
                "a route already exists for this source agent and trigger"
            )

        route = await self._load_route(
            db,
            source_agent_id=source_agent_id,
            route_id=inserted_id,
        )
        self._add_receipt(
            db,
            route=route,
            actor_admin_id=actor_admin_id,
            command_type="created",
            previous_target_agent_id=None,
            previous_is_active=None,
            applied=True,
            idempotency_key=key,
            command_hash=command_hash,
            occurred_at=event_time,
        )
        await db.flush()
        return AgentHandoffRouteResult(route=route, applied=True)

    async def update_route(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        route_id: uuid.UUID,
        target_agent_id: uuid.UUID | None,
        is_active: bool | None,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> AgentHandoffRouteResult:
        if target_agent_id is None and is_active is None:
            raise AgentHandoffRouteValidationError(
                "at least one route field must be provided"
            )
        key = self._required_key(idempotency_key)
        event_time = self._aware_utc(occurred_at or datetime.now(UTC))
        command_hash = self._command_hash(
            {
                "actor_admin_id": str(actor_admin_id),
                "command_type": "updated",
                "expected_version": expected_version,
                "is_active": is_active,
                "route_id": str(route_id),
                "source_agent_id": str(source_agent_id),
                "target_agent_id": (
                    str(target_agent_id) if target_agent_id is not None else None
                ),
            }
        )
        route, duplicate = await self._prepare_mutation(
            db,
            source_agent_id=source_agent_id,
            route_id=route_id,
            idempotency_key=key,
            command_hash=command_hash,
        )
        if duplicate:
            return AgentHandoffRouteResult(route=route, applied=False)
        self._assert_version(route, expected_version)

        effective_target_id = target_agent_id or route.target_agent_id
        await self._validate_agents(
            db,
            source_agent_id=source_agent_id,
            target_agent_id=effective_target_id,
        )
        effective_is_active = is_active if is_active is not None else route.is_active
        previous_target_agent_id = route.target_agent_id
        previous_is_active = route.is_active
        applied = (
            effective_target_id != route.target_agent_id
            or effective_is_active != route.is_active
        )
        if applied:
            route.target_agent_id = effective_target_id
            route.is_active = effective_is_active
            route.control_version += 1
            route.updated_by_admin_id = actor_admin_id
            route.updated_at = event_time

        self._add_receipt(
            db,
            route=route,
            actor_admin_id=actor_admin_id,
            command_type="updated",
            previous_target_agent_id=previous_target_agent_id,
            previous_is_active=previous_is_active,
            applied=applied,
            idempotency_key=key,
            command_hash=command_hash,
            occurred_at=event_time,
        )
        await db.flush()
        return AgentHandoffRouteResult(route=route, applied=applied)

    async def deactivate_route(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        route_id: uuid.UUID,
        actor_admin_id: uuid.UUID,
        expected_version: int,
        idempotency_key: str,
        occurred_at: datetime | None = None,
    ) -> AgentHandoffRouteResult:
        key = self._required_key(idempotency_key)
        event_time = self._aware_utc(occurred_at or datetime.now(UTC))
        command_hash = self._command_hash(
            {
                "actor_admin_id": str(actor_admin_id),
                "command_type": "deactivated",
                "expected_version": expected_version,
                "route_id": str(route_id),
                "source_agent_id": str(source_agent_id),
            }
        )
        route, duplicate = await self._prepare_mutation(
            db,
            source_agent_id=source_agent_id,
            route_id=route_id,
            idempotency_key=key,
            command_hash=command_hash,
        )
        if duplicate:
            return AgentHandoffRouteResult(route=route, applied=False)
        self._assert_version(route, expected_version)

        previous_is_active = route.is_active
        if route.is_active:
            route.is_active = False
            route.control_version += 1
            route.updated_by_admin_id = actor_admin_id
            route.updated_at = event_time
        self._add_receipt(
            db,
            route=route,
            actor_admin_id=actor_admin_id,
            command_type="deactivated",
            previous_target_agent_id=route.target_agent_id,
            previous_is_active=previous_is_active,
            applied=previous_is_active,
            idempotency_key=key,
            command_hash=command_hash,
            occurred_at=event_time,
        )
        await db.flush()
        return AgentHandoffRouteResult(route=route, applied=previous_is_active)

    async def _prepare_mutation(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        route_id: uuid.UUID,
        idempotency_key: str,
        command_hash: str,
    ) -> tuple[AgentHandoffRoute, bool]:
        receipt = await self._receipt_by_key(
            db,
            source_agent_id=source_agent_id,
            idempotency_key=idempotency_key,
        )
        if receipt is not None:
            self._assert_command_hash(receipt.command_hash, command_hash)
            route = await self._load_route(
                db,
                source_agent_id=source_agent_id,
                route_id=receipt.route_id,
            )
            return route, True

        route = await self._load_route(
            db,
            source_agent_id=source_agent_id,
            route_id=route_id,
            for_update=True,
        )
        receipt = await self._receipt_by_key(
            db,
            source_agent_id=source_agent_id,
            idempotency_key=idempotency_key,
        )
        if receipt is not None:
            self._assert_command_hash(receipt.command_hash, command_hash)
            return route, True
        return route, False

    async def _load_route(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        route_id: uuid.UUID,
        for_update: bool = False,
    ) -> AgentHandoffRoute:
        statement = select(AgentHandoffRoute).where(
            AgentHandoffRoute.id == route_id,
            AgentHandoffRoute.source_agent_id == source_agent_id,
        )
        if for_update:
            statement = statement.with_for_update()
        route = (await db.execute(statement)).scalar_one_or_none()
        if route is None:
            raise AgentHandoffRouteNotFoundError("handoff route not found")
        return route

    async def _receipt_by_key(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        idempotency_key: str,
    ) -> AgentHandoffRouteReceipt | None:
        return (
            await db.execute(
                select(AgentHandoffRouteReceipt).where(
                    AgentHandoffRouteReceipt.source_agent_id == source_agent_id,
                    AgentHandoffRouteReceipt.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()

    async def _validate_agents(
        self,
        db: AsyncSession,
        *,
        source_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
    ) -> None:
        if source_agent_id == target_agent_id:
            raise AgentHandoffRouteValidationError(
                "source and target agents must be different"
            )
        target = await db.get(AgentProfile, target_agent_id)
        if target is None or not target.is_active:
            raise AgentHandoffRouteValidationError(
                "target agent must exist and be active"
            )

    @staticmethod
    def _add_receipt(
        db: AsyncSession,
        *,
        route: AgentHandoffRoute,
        actor_admin_id: uuid.UUID,
        command_type: str,
        previous_target_agent_id: uuid.UUID | None,
        previous_is_active: bool | None,
        applied: bool,
        idempotency_key: str,
        command_hash: str,
        occurred_at: datetime,
    ) -> None:
        db.add(
            AgentHandoffRouteReceipt(
                route_id=route.id,
                source_agent_id=route.source_agent_id,
                actor_admin_id=actor_admin_id,
                command_type=command_type,
                trigger=route.trigger,
                previous_target_agent_id=previous_target_agent_id,
                target_agent_id=route.target_agent_id,
                previous_is_active=previous_is_active,
                is_active=route.is_active,
                control_version=route.control_version,
                applied=applied,
                idempotency_key=idempotency_key,
                command_hash=command_hash,
                created_at=occurred_at,
            )
        )

    @staticmethod
    def _trigger(value: AgentHandoffTrigger | str) -> AgentHandoffTrigger:
        try:
            return AgentHandoffTrigger(value)
        except ValueError as exc:
            raise AgentHandoffRouteValidationError(
                "unsupported handoff trigger"
            ) from exc

    @staticmethod
    def _required_key(value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 220:
            raise AgentHandoffRouteValidationError("invalid idempotency_key")
        return normalized

    @staticmethod
    def _command_hash(command: dict[str, object]) -> str:
        serialized = json.dumps(
            command,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(serialized).hexdigest()

    @staticmethod
    def _assert_command_hash(existing: str, requested: str) -> None:
        if not secrets.compare_digest(existing, requested):
            raise AgentHandoffRouteIdempotencyError(
                "idempotency key was reused for another command"
            )

    @staticmethod
    def _assert_version(route: AgentHandoffRoute, expected_version: int) -> None:
        if route.control_version != expected_version:
            raise AgentHandoffRouteVersionConflictError(
                "handoff route changed; reload before retrying"
            )

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


agent_handoff_route_service = AgentHandoffRouteService()
