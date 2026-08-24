# Saltacode public BFF

This service is the public, same-origin boundary between the Astro frontend and the private
`agent-ai` service. Browser clients never call an LLM provider or the private agent directly.

```text
browser -> public BFF -> private agent-ai -> authorized providers and tools
```

The current scaffold intentionally has no provider credentials, database, or transcript
persistence. Its default gateway emits a typed `agent_unavailable` SSE event until the private
agent adapter is implemented.

## Local development

```bash
uv sync --locked
uv run uvicorn app.main:app --reload
uv run ruff check .
uv run pytest
uv run python scripts/export_contracts.py --check
```

Configuration uses the `SALTACODE_` prefix:

```dotenv
SALTACODE_APP_ENV=development
SALTACODE_ALLOWED_ORIGINS=http://localhost:4321
SALTACODE_AGENT_AI_BASE_URL=http://agent-ai:8001
SALTACODE_AGENT_INTERNAL_TOKEN_FILE=/run/secrets/agent_internal_token
SALTACODE_RATE_LIMIT_BACKEND=memory
SALTACODE_RATE_LIMIT_REQUESTS=20
SALTACODE_RATE_LIMIT_WINDOW_SECONDS=60
```

`SALTACODE_AGENT_AI_BASE_URL` enables the HTTP adapter for the private
`POST /internal/v1/executions` endpoint. The adapter applies separate connection and response
timeouts, forwards `X-Correlation-ID`, validates response identity and shape, and converts private
transport/authentication/protocol failures into safe public SSE errors.

The private service requires a shared bearer token. Containers must receive it through
`SALTACODE_AGENT_INTERNAL_TOKEN_FILE`; the expected Compose secret path is
`/run/secrets/agent_internal_token`. Missing, unreadable, or shorter-than-32-character secret files
fail closed whenever the HTTP adapter is enabled outside tests. The backend never forwards the
token to clients or includes it in logs.

Local development may use the direct `SALTACODE_AGENT_INTERNAL_TOKEN` variable instead. Do not use
the direct value in production or commit it to an environment file. Development without a
configured base URL retains the safe unavailable stub.

`SALTACODE_ALLOWED_ORIGINS` is a comma-separated allowlist. Requests without an `Origin` header
remain valid for same-host and server-to-server operation; browser cross-origin POST requests are
rejected unless their exact origin is allowlisted.

## Client identity and rate limits

The in-memory fixed-window limiter is development/test-only. Production requires the atomic Redis
adapter:

```dotenv
SALTACODE_RATE_LIMIT_BACKEND=redis
SALTACODE_REDIS_URL=redis://redis:6379/0
SALTACODE_REDIS_CONNECT_TIMEOUT_SECONDS=1
SALTACODE_REDIS_RESPONSE_TIMEOUT_SECONDS=1
```

The Redis client uses a shared async pool and a Lua `INCR` plus `PEXPIRE` transaction, so concurrent
replicas make one authoritative fixed-window decision. Redis keys contain a SHA-256 digest instead
of the client address. Redis outages fail closed: readiness returns `503` and chat requests return a
safe `application/problem+json` response instead of bypassing abuse controls.

Because the only public ingress is host-managed Cloudflare Tunnel and the origin binds to loopback,
the BFF uses a syntactically validated `CF-Connecting-IP` when Cloudflare supplies it. It rejects
malformed or multi-value headers and otherwise falls back to the ASGI client address. It does not
trust `X-Forwarded-For`. Keeping the origin loopback-only is therefore part of the security contract.

SSE responses use `Cache-Control: no-store`, do not echo prompts, and carry a correlation ID.
The BFF does not log or persist request bodies.

Versioned JSON Schemas live in `../contracts/chat/v1/`. Regenerate them with:

```bash
uv run python scripts/export_contracts.py
```
