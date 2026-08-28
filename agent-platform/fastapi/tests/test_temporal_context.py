"""Deterministic regression tests for authoritative prompt time."""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "")

import pytest

from app.core.temporal_context import (
    ARGENTINA_TIMEZONE_NAME,
    build_temporal_context,
    render_authoritative_temporal_context,
)
from app.services.agent_loop import (
    _build_agent_system_prompt,
    build_agent_system_prompt_sections,
    compose_agent_system_prompt,
    run_agent_loop,
)


def test_utc_midnight_does_not_advance_argentina_date():
    before_argentina_midnight = datetime(2026, 8, 6, 1, 30, tzinfo=UTC)
    after_argentina_midnight = datetime(2026, 8, 6, 3, 1, tzinfo=UTC)

    before = build_temporal_context(before_argentina_midnight)
    after = build_temporal_context(after_argentina_midnight)

    assert before["fecha_actual"] == "2026-08-05"
    assert before["ayer"] == "2026-08-04"
    assert after["fecha_actual"] == "2026-08-06"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        build_temporal_context(datetime(2026, 8, 5, 12, 0))


def test_authoritative_block_contains_exact_date_and_precedence():
    ctx = build_temporal_context(datetime(2026, 8, 5, 15, 0, tzinfo=UTC))
    block = render_authoritative_temporal_context(ctx)

    assert ARGENTINA_TIMEZONE_NAME in block
    assert "Fecha actual exacta: 2026-08-05." in block
    assert "PRECEDENCIA OBLIGATORIA" in block
    assert "Un nombre de mes sin año NO determina por sí solo el año" in block
    assert "preguntá qué año corresponde" in block
    assert "refiere a ese mes del año de fecha_actual" not in block
    for lower_priority_source in (
        "historial",
        "memoria",
        "RAG",
        "bloque de conocimiento",
    ):
        assert lower_priority_source in block


def test_shared_compositor_is_exact_and_does_not_add_fake_sections():
    ctx = build_temporal_context(datetime(2026, 8, 5, 15, 0, tzinfo=UTC))
    profile = SimpleNamespace(
        name="Agente",
        prompt_identity="IDENTIDAD",
        prompt_domain="DOMINIO",
        prompt_guardrails="GUARDRAILS",
    )
    sections = build_agent_system_prompt_sections(profile, "KNOWLEDGE", ctx)
    composed = compose_agent_system_prompt(sections)

    assert composed == _build_agent_system_prompt(profile, "KNOWLEDGE", ctx)
    assert composed == "\n\n".join(section.content for section in sections)
    assert all(section.source != "memoria" for section in sections)
    assert sections[0].source_key == "app.core.temporal_context"
    assert sections[-1].source_key == "rag_policy"


@pytest.mark.asyncio
async def test_agent_loop_uses_one_context_for_knowledge_and_system_prompt(monkeypatch):
    ctx = build_temporal_context(datetime(2026, 8, 5, 15, 0, tzinfo=UTC))
    knowledge_builder = AsyncMock(return_value="DIRECTIVAS SIN FECHA")
    monkeypatch.setattr("app.services.agent_loop.build_temporal_context", lambda: ctx)
    monkeypatch.setattr(
        "app.services.agent_loop.knowledge_service.build_all_knowledge",
        knowledge_builder,
    )
    monkeypatch.setattr(
        "app.services.agent_loop.rag_retrieval_service.search",
        AsyncMock(return_value=[]),
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Respuesta.", tool_calls=None),
                )
            ]
        )
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await run_agent_loop(
            user_message="¿Qué día es hoy?",
            conversation_history=[
                {
                    "role": "assistant",
                    "content": "Hoy es 22 de julio de 2026.",
                }
            ],
            available_tools=[],
            tool_configs={},
            profile=None,
            user_id=uuid4(),
            phone="549test",
            request_id="req-temporal",
            db=object(),
            conversation_summary="La fecha actual es 28 de junio de 2026.",
        )

    assert result.status == "success"
    assert knowledge_builder.await_args.args[1] is ctx
    system_prompt = create.await_args.kwargs["messages"][0]["content"]
    assert "Fecha actual exacta: 2026-08-05." in system_prompt
    assert "PRECEDENCIA OBLIGATORIA" in system_prompt
    assert system_prompt.index("2026-08-05") < system_prompt.index("28 de junio")
