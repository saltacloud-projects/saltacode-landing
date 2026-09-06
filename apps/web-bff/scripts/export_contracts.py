import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from app.chat_v2.contracts import (
    BrowserMessageRequest,
    BrowserResetRequest,
    ConversationEvent,
    HistoryResponse,
    MessageAccepted,
    ResetResponse,
    StreamDone,
    StreamFailure,
)
from app.contracts import ChatRequest, ChatStreamEvent, ProblemDetails

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "chat"

CONTRACTS: dict[Path, dict[str, object]] = {
    Path("v1/request.schema.json"): ChatRequest.model_json_schema(),
    Path("v1/stream-event.schema.json"): TypeAdapter(ChatStreamEvent).json_schema(),
    Path("v1/problem.schema.json"): ProblemDetails.model_json_schema(),
    Path("v2/message-request.schema.json"): BrowserMessageRequest.model_json_schema(),
    Path("v2/message-accepted.schema.json"): MessageAccepted.model_json_schema(),
    Path("v2/history.schema.json"): HistoryResponse.model_json_schema(),
    Path("v2/stream-event.schema.json"): TypeAdapter(
        ConversationEvent | StreamFailure | StreamDone
    ).json_schema(),
    Path("v2/session-reset-request.schema.json"): BrowserResetRequest.model_json_schema(),
    Path("v2/session-reset-response.schema.json"): ResetResponse.model_json_schema(),
    Path("v2/problem.schema.json"): ProblemDetails.model_json_schema(),
}


def render(schema: dict[str, object]) -> str:
    document = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export versioned chat JSON Schemas.")
    parser.add_argument("--check", action="store_true", help="Fail when generated files drift.")
    args = parser.parse_args()

    drifted: list[Path] = []
    for relative_path, schema in CONTRACTS.items():
        path = CONTRACT_ROOT / relative_path
        expected = render(schema)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                drifted.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")

    if drifted:
        for path in drifted:
            print(f"contract drift: {path.relative_to(REPOSITORY_ROOT)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
