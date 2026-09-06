# Agent Platform

Channel-neutral AI agent service for web chat, WhatsApp, and authenticated API clients. It provides persistent conversation history, configurable agents, encrypted integration sources, source-bound tools, document retrieval, and an administration panel.

## Architecture

```text
web browser -> application BFF -> private web-chat v2 API
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
- Principals with route-scoped channel identities for web, WhatsApp, and API channels.
- Persisted conversations, messages, execution state, consent, and audit records.
- Encrypted integration credentials configured through the panel.
- HTTP sources with host allowlists, TLS enforcement, timeouts, size limits, and SSRF defenses.
- Tools bound to a source, HTTP method, channel allowlist, risk level, confirmation, and idempotency policy.
- Optional RAG worker and document administration.
- Meta webhook signature validation and optional WhatsApp access policy.
- Durable web execution and channel-neutral outbound workers with schema healthchecks.

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

The initialization script writes ignored local credentials to `.env.platform.local` and `.secrets/`. Do not commit either path. The BFF-to-agent token is mounted from `.secrets/internal_api_token`; it is not injected through Compose environment interpolation. The generated administrator must change the temporary password before any shared or production deployment.

Stop the stack with:

```bash
./scripts/platform/down.sh
```

The WhatsApp inbox, outbound delivery, and web execution workers are required
services. They run as one replica each, share the immutable API image, and have
provider egress without publishing ports. Inspect them with:

```bash
docker compose --env-file .env.platform.local ps
docker compose --env-file .env.platform.local exec outbound-worker \
  python /usr/local/libexec/agent-entrypoint.py \
  python -m app.workers.outbound --healthcheck
docker compose --env-file .env.platform.local exec web-execution-worker \
  python /usr/local/libexec/agent-entrypoint.py \
  python -m app.workers.web_executions --healthcheck
```

Worker healthchecks verify their local database schema and required storage.
They do not contact providers or decrypt/test provider credentials.

## Host release and rollback

The agent platform has its own fail-closed host release boundary; it is never deployed or rolled back by the landing scripts.

```bash
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  ./scripts/platform/preflight-release.sh

# Explicit production authorization is required before this command.
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  ./scripts/platform/deploy-release.sh
```

The deploy uses an immutable `APP_VERSION`, controlled one-shot migrations,
`docker compose --wait`, internal and loopback health probes, and secret-free
version 3 receipts under `/var/lib/saltacode-agent-platform`. The receipts bind
all required workers to the API image and record their health. Rollback preserves
PostgreSQL, documents, conversation history, and audit data; it refuses a target
whose database revision or runtime contract is incompatible.

See [`docs/operations/release-and-rollback.md`](docs/operations/release-and-rollback.md) for environment preparation, exact rollback commands, receipt fields, and the schema-change boundary.

## Configuration workflow

1. Sign in and create reusable provider, channel, and API connections in the platform library.
2. Create an integration source with its base URL, allowed hosts, authentication scheme, transport policy, and write-only encrypted credentials.
3. Test source connectivity, then create tools bound to that source with an explicit method, parameter location, channel, and risk policy.
4. Select an agent and assign only the sources, tools, knowledge blocks, document areas, and WhatsApp users it may use.
5. Configure that agent's provider runtime and its server-owned web or WhatsApp routes.
6. Validate the selected persisted agent in PromptLab before exposing it to a public channel.

Write-capable tools are never inferred from user text. They require trusted configuration, channel authorization, explicit confirmation, and an idempotency strategy.

See [`docs/architecture/administration-model.md`](docs/architecture/administration-model.md) for the complete hierarchy, persisted/editable configuration, write-only secret boundary, channel routing, and current global-audit limitation.

## Development

```bash
cd api
uv sync --locked
# Hermetic tests; integration tests are excluded by default.
uv run pytest -q
uv run ruff check .
uv run pip-audit

cd ..
# PostgreSQL integration tests run in an isolated test image with dev dependencies.
docker compose --env-file .env.platform.local --profile test run --rm integration-tests

cd panel
npm ci
npm run build
```

The production API image installs only runtime dependencies and excludes tests
and maintenance scripts. The dedicated `test` build target owns the test suite
and development tools. A non-development container fails closed when the
internal API token file is absent, the JWT secret is weak, either contact key is
unavailable, or the independent contact encryption and lookup keys contain the
same material.

The clean platform schema lives in `api/migrations_platform/` and is selected with `api/alembic-platform.ini`.
The administration panel intentionally uses npm and its committed `package-lock.json`; the repository landing uses pnpm from the repository root.

## Documentation

- `docs/architecture/platform.md`
- `docs/architecture/administration-model.md`
- `docs/operations/local-stack.md`
- `docs/operations/release-and-rollback.md`
- `docs/security/trust-boundaries.md`
- `docs/tools/http-sources.md`
