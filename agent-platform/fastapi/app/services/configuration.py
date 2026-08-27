"""Capability-oriented readiness for the agent platform."""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent_profile import AgentProfile
from app.models.integration_source import IntegrationSource
from app.models.knowledge_block import KnowledgeBlock
from app.models.tool_config import ToolConfig
from app.services.tools.registry import tool_registry

logger = logging.getLogger(__name__)

REQUIRED_BLOCKS: list[str] = []
RECOMMENDED_BLOCKS: list[str] = []


@dataclass
class ConfigIssue:
    level: str  # "error" | "warning"
    category: str  # "profile" | "knowledge" | "tools" | "credentials"
    message: str


@dataclass
class ConfigStatus:
    is_ready: bool
    issues: list[ConfigIssue] = field(default_factory=list)


class ConfigurationService:
    async def check(self, db: AsyncSession) -> ConfigStatus:
        """
        Verifica el estado completo de configuración del agente.
        Retorna ConfigStatus con is_ready=True si todo lo crítico está OK.
        """
        issues: list[ConfigIssue] = []

        # 1. Default public agent
        profile = (
            await db.execute(
                select(AgentProfile)
                .where(
                    AgentProfile.slug == settings.default_agent_slug,
                    AgentProfile.is_active == True,  # noqa: E712
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if not profile:
            issues.append(
                ConfigIssue(
                    "error", "profile", "No active default agent profile is configured"
                )
            )
        else:
            if not profile.prompt_identity or not profile.prompt_identity.strip():
                issues.append(
                    ConfigIssue(
                        "error", "profile", "El perfil activo no tiene prompt_identity"
                    )
                )
            if not profile.prompt_guardrails or not profile.prompt_guardrails.strip():
                issues.append(
                    ConfigIssue(
                        "warning",
                        "profile",
                        "El perfil activo no tiene prompt_guardrails",
                    )
                )

        # 2. Knowledge blocks requeridos
        blocks = await db.execute(select(KnowledgeBlock.key, KnowledgeBlock.is_enabled))
        blocks_map = {row[0]: row[1] for row in blocks.all()}

        for key in REQUIRED_BLOCKS:
            if key not in blocks_map:
                issues.append(
                    ConfigIssue(
                        "error", "knowledge", f"Falta el bloque requerido '{key}'"
                    )
                )
            elif not blocks_map[key]:
                issues.append(
                    ConfigIssue(
                        "error", "knowledge", f"El bloque '{key}' está deshabilitado"
                    )
                )

        for key in RECOMMENDED_BLOCKS:
            if key not in blocks_map:
                issues.append(
                    ConfigIssue(
                        "warning", "knowledge", f"Falta el bloque recomendado '{key}'"
                    )
                )
            elif not blocks_map[key]:
                issues.append(
                    ConfigIssue(
                        "warning", "knowledge", f"El bloque '{key}' está deshabilitado"
                    )
                )

        # 3. Tools habilitadas en DB con adapter runtime registrado
        enabled_tools = (
            (
                await db.execute(
                    select(ToolConfig.tool_name).where(ToolConfig.is_enabled == True)  # noqa: E712
                )
            )
            .scalars()
            .all()
        )
        runtime_tools = set(tool_registry.list_tools())

        orphan_db = [t for t in enabled_tools if t not in runtime_tools]
        if orphan_db:
            issues.append(
                ConfigIssue(
                    "warning",
                    "tools",
                    f"Tools habilitadas en DB sin adapter runtime: {', '.join(orphan_db)}",
                )
            )

        if not enabled_tools:
            issues.append(ConfigIssue("warning", "tools", "No hay tools habilitadas"))

        active_sources = (
            (
                await db.execute(
                    select(IntegrationSource).where(IntegrationSource.is_active == True)  # noqa: E712
                )
            )
            .scalars()
            .all()
        )
        sources_without_credentials = [
            source.slug
            for source in active_sources
            if source.auth_type != "none" and not source.encrypted_credentials
        ]
        if sources_without_credentials:
            issues.append(
                ConfigIssue(
                    "warning",
                    "sources",
                    "Sources missing credentials: "
                    + ", ".join(sources_without_credentials),
                )
            )

        # 4. Provider and optional channels
        if not settings.openai_api_key:
            issues.append(
                ConfigIssue("error", "credentials", "OPENAI_API_KEY no configurada")
            )
        if not settings.whatsapp_token:
            issues.append(
                ConfigIssue("warning", "credentials", "WHATSAPP_TOKEN no configurado")
            )
        else:
            missing_whatsapp = [
                name
                for name, value in (
                    ("WHATSAPP_PHONE_NUMBER_ID", settings.whatsapp_phone_number_id),
                    ("WHATSAPP_VERIFY_TOKEN", settings.whatsapp_verify_token),
                    ("WHATSAPP_APP_SECRET", settings.whatsapp_app_secret),
                )
                if not value
            ]
            if missing_whatsapp:
                issues.append(
                    ConfigIssue(
                        "error",
                        "credentials",
                        "WhatsApp channel missing: " + ", ".join(missing_whatsapp),
                    )
                )

        # is_ready = sin errores críticos (los warnings no bloquean)
        has_errors = any(i.level == "error" for i in issues)
        return ConfigStatus(is_ready=not has_errors, issues=issues)


configuration_service = ConfigurationService()
