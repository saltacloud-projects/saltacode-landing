# Saltacode Agent Service

Private FastAPI service that will host Saltacode's AI orchestration. This seed
establishes contracts and trust boundaries; it does not ship a model provider,
RAG adapter, business tools, transcript store, or public browser endpoint.

## Boundary

```text
browser -> public backend/BFF -> private agent-ai service
```

- Only the backend/BFF may call `/internal/v1/executions`.
- Internal requests require a bearer token supplied at runtime.
- The seed runtime intentionally returns `503` until adapters are configured.
- Prompts and transcripts are not persisted.
- Model, knowledge, and tool integrations implement application ports instead
  of being hardcoded into the service.

## Local development

```bash
cd agent-ai
uv sync
export SALTACODE_AGENT_INTERNAL_TOKEN="$(openssl rand -hex 32)"
uv run uvicorn saltacode_agent.transport.http.app:create_app \
  --factory --host 127.0.0.1 --port 8001 --reload
```

The direct `SALTACODE_AGENT_INTERNAL_TOKEN` variable is accepted only in
`development` and `testing`. Production must mount a Docker secret and point to
it without putting the token in Compose or process environment values:

```text
SALTACODE_AGENT_ENVIRONMENT=production
SALTACODE_AGENT_INTERNAL_TOKEN_FILE=/run/secrets/saltacode_agent_internal_token
```

The secret file must be readable by container UID `10001` and contain at least
32 characters. A trailing newline is accepted. Startup fails closed when the
file is missing, unreadable, oversized, too short, or configured together with
the direct token. The token value is never logged.

The service listens on internal container port `8001`; Compose must not publish
that port to the host. It exposes these internal endpoints:

- `GET /health/live` — process liveness.
- `GET /health/ready` — adapter readiness; initially returns `503`.
- `POST /internal/v1/executions` — versioned execution contract.

## Quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

See [`UPSTREAM.md`](UPSTREAM.md) for the allowlisted Metalnor provenance and
the categories that were deliberately excluded.
