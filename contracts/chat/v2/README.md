# Chat contract v2

The browser uses durable commands and resumable server-sent events through the same-origin BFF:

- `POST /api/v2/chat/messages` accepts `message-request.schema.json` and returns
  `message-accepted.schema.json` only after durable acceptance.
- `GET /api/v2/chat/history` returns `history.schema.json` as the server-authoritative transcript.
- `GET /api/v2/chat/events` emits frames matching `stream-event.schema.json`. Persisted events carry
  monotonic cursors and can be resumed with `Last-Event-ID`.
- `POST /api/v2/chat/session/reset` accepts `session-reset-request.schema.json` and returns
  `session-reset-response.schema.json`.

Pre-stream HTTP failures use `application/problem+json` and `problem.schema.json`. Once streaming has
started, a temporary dependency failure is represented by the failure and done variants in
`stream-event.schema.json`.

These are consumer-owned public contracts. Private Agent Platform payloads and identifiers are not
exported here. Run `uv run python scripts/export_contracts.py` from `apps/web-bff/` after changing a
contract and commit the Python models and generated schemas together.
