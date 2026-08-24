# Chat contract v1

The browser sends `request.schema.json` to `POST /api/v1/chat`. A successful response uses
`text/event-stream`; every `data` line validates against `stream-event.schema.json` and its SSE
`event` field matches the payload `type` discriminator.

HTTP failures before streaming starts use `application/problem+json` and
`problem.schema.json`. Once streaming has started, failures are represented by `chat.error`
followed by `chat.done`.

These files are generated from the Python models. Run `uv run python scripts/export_contracts.py`
from `backend/` after changing a contract and commit model and schema changes together.
