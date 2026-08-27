"""Regresión del acople RAG automático dentro del agent loop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.agent_loop import run_agent_loop
from app.services.rag.types import RagHit


@pytest.mark.asyncio
async def test_agent_loop_injects_rag_evidence_and_returns_trace(monkeypatch):
    area_id = uuid4()
    hit = RagHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        reference_code="DOC-AABBCCDD",
        title="Procedimiento",
        version_number=3,
        content="El responsable autoriza la orden.",
        page_number=2,
        location_label="Página 2",
        section_title=None,
        score=0.91,
    )
    search = AsyncMock(return_value=[hit])
    monkeypatch.setattr("app.services.agent_loop.rag_retrieval_service.search", search)
    monkeypatch.setattr(
        "app.services.agent_loop.knowledge_service.build_all_knowledge",
        AsyncMock(return_value=""),
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="La orden debe ser autorizada.", tool_calls=None
                    ),
                )
            ]
        )
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await run_agent_loop(
            user_message="¿Quién autoriza la orden?",
            conversation_history=[],
            available_tools=[],
            tool_configs={},
            profile=None,
            user_id=uuid4(),
            phone="549test",
            request_id="req-rag",
            db=object(),
            rag_area_ids_override={area_id},
        )

    assert result.status == "success"
    assert result.response_text == "La orden debe ser autorizada."
    assert result.rag_hits[0]["chunk_id"] == str(hit.chunk_id)
    assert result.rag_hits[0]["reference_code"] == "DOC-AABBCCDD"
    assert search.await_args.kwargs["area_ids_override"] == {area_id}
    sent_messages = create.await_args.kwargs["messages"]
    assert "EVIDENCIA_RAG_NO_CONFIABLE" in sent_messages[-1]["content"]
    assert "no los muestres al usuario" in sent_messages[-1]["content"]


@pytest.mark.asyncio
async def test_agent_loop_degrades_when_retrieval_fails(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_loop.rag_retrieval_service.search",
        AsyncMock(side_effect=RuntimeError("vector unavailable")),
    )
    monkeypatch.setattr(
        "app.services.agent_loop.knowledge_service.build_all_knowledge",
        AsyncMock(return_value=""),
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="Respuesta sin RAG.", tool_calls=None
                    ),
                )
            ]
        )
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch("openai.AsyncOpenAI", return_value=fake_client):
        result = await run_agent_loop(
            user_message="consulta",
            conversation_history=[],
            available_tools=[],
            tool_configs={},
            profile=None,
            user_id=uuid4(),
            phone="549test",
            request_id="req-degraded",
            db=object(),
        )

    assert result.status == "success"
    assert result.response_text == "Respuesta sin RAG."
    assert result.rag_hits == []
