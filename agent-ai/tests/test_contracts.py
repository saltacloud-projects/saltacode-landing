from uuid import uuid4

import pytest
from pydantic import ValidationError

from saltacode_agent.domain.contracts import ExecutionRequest, ToolResult, ToolStatus


def test_execution_request_is_stateless_and_rejects_transcript_fields() -> None:
    payload = {
        "request_id": uuid4(),
        "session_id": uuid4(),
        "input": "Necesito asesoramiento.",
        "locale": "es-AR",
        "history": [{"role": "user", "content": "secret"}],
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExecutionRequest.model_validate(payload)


def test_tool_model_summary_is_not_serialized() -> None:
    result = ToolResult(
        request_id=uuid4(),
        tool_name="catalog.search",
        status=ToolStatus.SUCCEEDED,
        output={"items": 20},
        model_summary={"count": 20},
    )

    assert "model_summary" not in result.model_dump()
