# Agent Platform

Channel-neutral AI agent service for web chat, WhatsApp, and authenticated API clients. It provides persistent conversation history, configurable agents, encrypted integration sources, source-bound tools, document retrieval, and an administration panel.

## Architecture

```text
web browser -> application BFF -> POST /internal/v1/executions
Meta webhook ------------------> WhatsApp adapter
trusted clients ---------------> authenticated API adapter
                                      |
                                      v
                          chat application service
                         /          |            \
                 agents       conversations     tool policy
                                                   |
                                    integration source adapters
```

The browser never receives provider keys, integration credentials, or the internal execution token. WhatsApp is an adapter, not the platform identity.

## Capabilities

- Independent agent profiles with public/private visibility and retention settings.
- Principals and channel identities shared across web, WhatsApp, and API channels.
- Persisted conversations, messages, execution state, consent, and audit records.
- Encrypted integration credentials configured through the panel.
- HTTP sources with host allowlists, TLS enforcement, timeouts, size limits, and SSRF defenses.
- Tools bound to a source, HTTP method, channel allowlist, risk level, confirmation, and idempotency policy.
- Optional RAG worker and document administration.
- Meta webhook signature validation and optional WhatsApp access policy.

## Local stack

Requirements: Docker Engine with Compose v2.

```bash
./scripts/platform/init-local-secrets.sh
./scripts/platform/up.sh
```

Default local endpoints:

| Service | URL |
|---|---|
| Administration panel | `http://127.0.0.1:23000` |
| Agent API and OpenAPI | `http://127.0.0.1:28082/docs` |
| Agent readiness | `http://127.0.0.1:28082/ready` |

The initialization script writes ignored local credentials to `.env.platform.local` and `.secrets/`. Do not commit either path. The generated administrator must change the temporary password before any shared or production deployment.

Stop the stack with:

```bash
./scripts/platform/down.sh
```

## Configuration workflow

1. Sign in to the panel.
2. Create an integration source with its base URL, allowed hosts, authentication scheme, and encrypted credentials.
3. Test source connectivity from the panel.
4. Create tools bound to that source and explicitly select method, parameter location, channels, and risk policy.
5. Enable tools only for the channels that may use them and mark web-visible sources public explicitly.
6. Configure the agent profile and knowledge, then validate in Prompt Lab before exposing it to a public channel.

Write-capable tools are never inferred from user text. They require trusted configuration, channel authorization, explicit confirmation, and an idempotency strategy.

## Development

```bash
cd fastapi
uv sync --locked
uv run pytest -q
uv run ruff check .

cd ../frontend
npm ci
npm run build
```

The clean platform schema lives in `fastapi/migrations_platform/` and is selected with `fastapi/alembic-platform.ini`.

## Documentation

- `docs/architecture/platform.md`
- `docs/operations/local-stack.md`
- `docs/security/trust-boundaries.md`
- `docs/tools/http-sources.md`
