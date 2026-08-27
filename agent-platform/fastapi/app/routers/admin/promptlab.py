"""
Agent Platform — Router: Admin PromptLab
/api/admin/promptlab/* — preview del system prompt y test del agente.
"""

import logging
import time
import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.temporal_context import build_temporal_context
from app.dependencies import get_db
from app.models.admin_user import AdminUser
from app.models.authorized_user import AuthorizedUser
from app.models.conversation_message import ConversationMessage
from app.models.rag import OrganizationArea
from app.models.tool_config import ToolConfig
from app.routers.admin.auth import require_admin, require_permission
from app.schemas.tools import ToolExecutionContext
from app.services.admin_rbac import AdminPermission
from app.services.agent_loop import (
    _build_agent_system_prompt,
    build_agent_system_prompt_sections,
    compose_agent_system_prompt,
    run_agent_loop,
)
from app.services.agent_profile import agent_profile_service
from app.services.knowledge import knowledge_service
from app.services.tool_policy import tool_policy_service
from app.services.tools.registry import tool_registry

router = APIRouter(
    tags=["admin-promptlab"],
    dependencies=[Depends(require_permission(AdminPermission.PROMPTLAB_USE))],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PromptPreviewRequest(BaseModel):
    """Puede enviar overrides parciales del perfil o knowledge para preview."""

    prompt_identity_override: str | None = None
    prompt_domain_override: str | None = None
    prompt_guardrails_override: str | None = None
    directives_override: str | None = None


class PromptPreviewResponse(BaseModel):
    system_prompt: str
    char_count: int
    profile_name: str | None
    placeholders_resolved: list[str]


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class TestAgentRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_history: list[
        ChatMessage
    ] = []  # mensajes anteriores para mantener contexto
    phone_override: str | None = None
    user_id: str | None = None
    area_ids: list[str] = Field(default_factory=list)


class TestAgentResponse(BaseModel):
    response_text: str
    tools_used: list[str]
    tool_invocations: list[dict] = []
    iterations: int
    total_tool_calls: int
    duration_ms: int
    status: str
    rag_hits: list[dict] = Field(default_factory=list)


class ConversationSearchResult(BaseModel):
    id: str
    phone_number: str
    role: str
    content: str
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class PromptSection(BaseModel):
    name: str
    source: str  # "perfil", "knowledge_block", "codigo", "memoria"
    source_key: str | None = None  # key del KB o campo del perfil
    content: str
    char_count: int


class PromptStructureResponse(BaseModel):
    sections: list[PromptSection]
    system_prompt: str
    total_chars: int
    tools_count: int
    tools_list: list[str]


@router.get("/prompt-structure", response_model=PromptStructureResponse)
async def prompt_structure(db: AsyncSession = Depends(get_db)):
    """
    Devuelve la estructura completa del system prompt desglosada por secciones,
    indicando el origen de cada una (perfil, knowledge_block, codigo, memoria).
    """
    # Build the same request-scoped inputs and use the same compositor as runtime.
    temporal_context = build_temporal_context()
    profile = await agent_profile_service.get_active_profile(db, redis=None)
    resolved_knowledge = await knowledge_service.build_resolved_knowledge(
        db,
        temporal_context,
        agent_id=profile.id if profile else None,
    )
    knowledge = knowledge_service.compose_resolved_knowledge(resolved_knowledge)
    composed_sections = build_agent_system_prompt_sections(
        profile,
        knowledge,
        temporal_context,
    )
    sections: list[PromptSection] = []
    for section in composed_sections:
        if section.source == "knowledge_block":
            sections.extend(
                PromptSection(
                    name=block.title,
                    source="knowledge_block",
                    source_key=block.key,
                    content=block.content,
                    char_count=len(block.content),
                )
                for block in resolved_knowledge
            )
            continue
        sections.append(
            PromptSection(
                name=section.name,
                source=section.source,
                source_key=section.source_key,
                content=section.content,
                char_count=len(section.content),
            )
        )
    system_prompt = compose_agent_system_prompt(composed_sections)
    if system_prompt != "\n\n".join(section.content for section in sections):
        raise RuntimeError("PromptLab section breakdown diverged from runtime prompt")

    # Tools
    from app.services.tools.dynamic import sync_http_api_tools

    await sync_http_api_tools(db)
    runtime = sorted(tool_registry.list_tools())

    return PromptStructureResponse(
        sections=sections,
        system_prompt=system_prompt,
        total_chars=len(system_prompt),
        tools_count=len(runtime),
        tools_list=runtime,
    )


@router.post("/prompt-preview", response_model=PromptPreviewResponse)
async def prompt_preview(
    data: PromptPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Arma y retorna el system prompt completo tal como lo vería el LLM.
    Permite overrides parciales para previsualizar cambios antes de guardarlos.
    """
    persisted_profile = await agent_profile_service.get_active_profile(db, redis=None)
    profile = None
    if persisted_profile:
        # Overrides are preview-only. Use a plain detached value object so the
        # request dependency's automatic commit can never persist a preview.
        profile = SimpleNamespace(
            name=persisted_profile.name,
            prompt_identity=persisted_profile.prompt_identity,
            prompt_domain=persisted_profile.prompt_domain,
            prompt_guardrails=persisted_profile.prompt_guardrails,
        )

    # Aplicar overrides al perfil si se enviaron
    if profile and data.prompt_identity_override is not None:
        profile.prompt_identity = data.prompt_identity_override
    if profile and data.prompt_domain_override is not None:
        profile.prompt_domain = data.prompt_domain_override
    if profile and data.prompt_guardrails_override is not None:
        profile.prompt_guardrails = data.prompt_guardrails_override

    # Construir knowledge (todos los bloques habilitados)
    temporal_context = build_temporal_context()
    if data.directives_override is not None:
        knowledge = data.directives_override
    else:
        knowledge = await knowledge_service.build_all_knowledge(
            db,
            temporal_context,
            agent_id=persisted_profile.id if persisted_profile else None,
        )

    system_prompt = _build_agent_system_prompt(profile, knowledge, temporal_context)
    placeholders = list(temporal_context.keys())

    return PromptPreviewResponse(
        system_prompt=system_prompt,
        char_count=len(system_prompt),
        profile_name=profile.name if profile else None,
        placeholders_resolved=placeholders,
    )


@router.post("/test-agent", response_model=TestAgentResponse)
async def test_agent(
    data: TestAgentRequest,
    admin: AdminUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Ejecuta una pregunta de prueba contra el agent loop real.
    NO persiste la conversación. Usa tools reales habilitadas para el agente.
    """
    request_id = str(uuid.uuid4())
    authorized_user = None
    if data.user_id:
        try:
            authorized_user = (
                await db.execute(
                    select(AuthorizedUser).where(
                        AuthorizedUser.id == uuid.UUID(data.user_id),
                        AuthorizedUser.is_active == True,  # noqa: E712
                    )
                )
            ).scalar_one_or_none()
        except ValueError:
            authorized_user = None
    phone = data.phone_override or (
        authorized_user.phone_number if authorized_user else "admin_test"
    )
    agent_user_id = authorized_user.id if authorized_user else admin.id
    if data.area_ids:
        try:
            rag_area_ids = {uuid.UUID(value) for value in data.area_ids}
        except ValueError:
            rag_area_ids = set()
    elif authorized_user:
        rag_area_ids = None
    else:
        rag_area_ids = set(
            (
                await db.execute(
                    select(OrganizationArea.id).where(
                        OrganizationArea.is_general == True,  # noqa: E712
                        OrganizationArea.is_active == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )

    # Cargar perfil y tools como haría el pipeline
    profile = await agent_profile_service.get_active_profile(db, redis=None)
    from app.services.tools.dynamic import sync_http_api_tools

    await sync_http_api_tools(db)
    runtime_tools = set(tool_registry.list_tools())
    execution_context = ToolExecutionContext(
        request_id=request_id,
        channel="whatsapp",
        principal_id=str(agent_user_id),
        agent_id=str(profile.id) if profile else None,
        external_subject=phone,
        scopes={"tools:read", "tools:write"},
    )
    available_tools = await tool_policy_service.available_tools(
        db,
        execution_context,
        runtime_tools,
    )
    all_tool_configs_result = await db.execute(
        select(ToolConfig).where(ToolConfig.is_enabled == True)  # noqa: E712
    )
    tool_configs = {
        t.tool_name: {
            "params_schema": t.params_schema or {},
            "timeout_seconds": t.timeout_seconds,
        }
        for t in all_tool_configs_result.scalars().all()
    }
    logger.info(
        "admin_test_agent",
        extra={
            "admin_email": admin.email,
            "message_preview": data.message[:80],
            "request_id": request_id,
        },
    )

    # Convertir historial del frontend al formato OpenAI
    history = [
        {"role": m.role, "content": m.content} for m in data.conversation_history
    ]

    start = time.monotonic()
    result = await run_agent_loop(
        user_message=data.message,
        conversation_history=history,
        available_tools=available_tools,
        tool_configs=tool_configs,
        profile=profile,
        user_id=agent_user_id,
        phone=phone,
        request_id=request_id,
        db=db,
        conversation_summary=None,
        rag_area_ids_override=rag_area_ids,
        rag_allow_disabled=True,
        execution_context=execution_context,
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    return TestAgentResponse(
        response_text=result.response_text,
        tools_used=result.tools_used,
        tool_invocations=result.tool_invocations,
        iterations=result.iterations,
        total_tool_calls=result.total_tool_calls,
        duration_ms=duration_ms,
        status=result.status,
        rag_hits=result.rag_hits,
    )


@router.get("/search-conversations", response_model=list[ConversationSearchResult])
async def search_conversations(
    q: str = Query(min_length=2),
    phone: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Busca texto en el contenido de los mensajes de conversación."""
    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.content.ilike(f"%{q}%"))
        .order_by(ConversationMessage.created_at.desc())
        .limit(limit)
    )
    if phone:
        stmt = stmt.where(ConversationMessage.phone_number == phone)

    result = await db.execute(stmt)
    return [
        ConversationSearchResult(
            id=str(m.id),
            phone_number=m.phone_number,
            role=m.role,
            content=m.content[:500],
            created_at=m.created_at.isoformat(),
        )
        for m in result.scalars().all()
    ]
