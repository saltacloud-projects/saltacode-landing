# SaltaCode Platform

SaltaCode's landing platform combines a static-first Astro frontend, a public FastAPI BFF, versioned chat contracts, and a channel-neutral agent platform in one repository. The marketing surface remains indexable without client JavaScript and the chat is isolated from the critical rendering path.

## Architecture

```text
browser -> frontend static origin and same-origin /api proxy
                                |
                                v
                       public FastAPI BFF
                         |            |
                         v            v
                private Redis   private agent platform
                                      |
                            approved APIs and providers
```

- Application images are built locally and orchestrated with Docker Compose.
- Cloudflare Tunnel remains host-managed; there is no host Nginx or Caddy requirement.
- The browser never receives provider keys or the internal agent token.
- The BFF owns origin checks, rate limiting, consent, a signed HttpOnly chat session, contract validation, and SSE adaptation.
- `agent-platform/` owns agents, multi-channel history, encrypted sources, tool policies, WhatsApp, RAG, and provider orchestration as an independent deployable unit.

## Local integrated stack

The agent platform is a normal versioned folder in this repository:

```text
agent-platform/
```

Start the complete local stack:

```bash
./scripts/local/up.sh
```

Default endpoints:

| Service | URL |
|---|---|
| Landing and web chat | `http://127.0.0.1:28080` |
| SaltaCode BFF / OpenAPI | `http://127.0.0.1:28081/docs` |
| Agent API / OpenAPI | `http://127.0.0.1:28082/docs` |
| Agent administration panel | `http://127.0.0.1:23000` |

The start script also exposes the same ports on the trusted LAN for phone and tablet review. It generates ignored local secrets and credentials; nothing is committed.

Stop both stacks with:

```bash
./scripts/local/down.sh
```

## Validation

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm check
pnpm test

(cd backend && uv sync --locked --all-groups && uv run ruff format --check . \
  && uv run ruff check . && uv run pytest \
  && uv run python scripts/export_contracts.py --check)

(cd agent-platform/fastapi && uv sync --locked && uv run ruff format --check app tests \
  && uv run ruff check app tests)

(cd agent-platform/frontend && npm ci && npm run build \
  && npm audit --audit-level=moderate)

bash scripts/agentic/validate-layer.sh
docker compose --env-file .env.sandbox.local \
  -f compose.yml -f compose.sandbox.yml config --quiet
(cd agent-platform && docker compose --env-file .env.platform.local config --quiet)
```

## Repository map

| Path | Purpose |
|---|---|
| `frontend/` | Astro, TypeScript, static SEO surface, optimized assets, lazy chat client, and same-origin proxy. |
| `backend/` | Public FastAPI BFF, signed session, SSE contract, origin checks, correlation, and shared rate limiting. |
| `agent-platform/` | Neutral agent API, administration panel, sources, tools, histories, migrations, and its container stack. |
| `contracts/chat/v1/` | Versioned browser-to-BFF JSON Schemas. |
| `compose.yml` | Site/BFF/Redis topology connected to the private agent service network. |
| `infrastructure/` | Host-managed Tunnel templates and site release verification. |
| `.codex/`, `.agents/skills/` | Scoped agents and reusable project skills. |
| `docs/discovery/` | Dated evidence snapshots and explicitly unknown external state. |
| `docs/quality/` | SEO, accessibility, and performance gates. |
| `docs/architecture/` | Technology, trust-boundary, and runtime decisions. |

## Delivery rules

1. Keep changes in bounded work units and validate before a Conventional Commit.
2. Preserve public URLs, canonical intent, indexable content, contact paths, real 404 behavior, and structured data.
3. Measure preview and deployed responses before claiming ranking or performance improvements.
4. Never commit provider secrets or expose the agent directly to browser code.
5. Do not push, deploy, install services, change DNS, or mutate Cloudflare without explicit authorization.

Repository checks prove generated HTML, contracts, topology, and local behavior. Only deployed-response checks, provider evidence, Search Console, and field Core Web Vitals can prove production impact.
