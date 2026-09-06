# SaltaCode Platform

SaltaCode's landing platform combines a static-first Astro frontend, a public FastAPI BFF, versioned chat contracts, and a channel-neutral agent platform in one repository. The marketing surface remains indexable without client JavaScript and the chat is isolated from the critical rendering path.

## Architecture

```text
browser -> frontend static origin and same-origin /api proxy
                                |
                                v
                       minimal public FastAPI BFF
                         |            |
                         v            v
                private Redis   repository-owned Agent Platform
                                      |
                   control + commercial orchestration + workers
                                      |
                            approved APIs and providers
```

- Application images are built locally and orchestrated with Docker Compose.
- Cloudflare Tunnel remains host-managed; there is no host Nginx or Caddy requirement.
- The browser never receives provider keys or the internal agent token.
- The BFF owns only the public trust boundary: origin checks, rate limiting, consent-version validation, a signed HttpOnly chat session, contract adaptation, and SSE forwarding.
- `agent-platform/` is repository-owned and independently deployable. It owns agents, web chat v2, provider-neutral external ingress, multi-channel history, human and acting-agent control, encrypted sources, commercial state, durable workers, RAG, and provider orchestration.
- External-channel ingress is provider-neutral after authentication: payloads are encrypted at rest, ordered per thread, and quarantined for operator review when execution is uncertain. WhatsApp is the only executable external adapter today.

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

Install each deployable's locked dependencies once, then run the complete repository gate from the root:

```bash
corepack enable
pnpm install --frozen-lockfile
(cd apps/web-bff && uv sync --locked --all-groups)
(cd agent-platform/api && uv sync --locked --all-groups)
(cd agent-platform/panel && npm ci && npx playwright install chromium)
pnpm verify
```

`pnpm verify` checks the frontend, BFF, agent API, administration panel, Compose models, shell scripts, and agentic contracts. It provisions and removes an ephemeral pgvector/PostgreSQL container for the agent integration tests unless `AGENT_TEST_POSTGRES_DSN` points to a disposable test database. Focused gates remain available as `pnpm verify:frontend`, `pnpm verify:backend`, `pnpm verify:agent-api`, `pnpm verify:agent-panel`, `pnpm verify:infrastructure`, and `pnpm verify:agentic`.

For repository-local agentic maintenance, run the read-only workstation preflight and structural contract gate separately:

```bash
bash scripts/agentic/doctor.sh
bash scripts/agentic/validate-layer.sh
```

The doctor fails only for required local capabilities. Recommended tools and external integrations are reported without treating absence, authentication, or provider health as repository failure.

## Repository map

| Path | Purpose |
|---|---|
| `apps/landing/` | Astro, TypeScript, static SEO surface, optimized assets, lazy chat client, and same-origin proxy. |
| `apps/web-bff/` | Public FastAPI BFF, signed session, SSE contract, origin checks, correlation, and shared rate limiting. |
| `agent-platform/api/` | Repository-owned agent runtime, web v2, external-channel ingress, human control, commercial orchestration, workers, and migrations. |
| `agent-platform/panel/` | Agent-scoped administration and operations UI for inbox, external ingress review, opportunities, follow-ups, meetings, delivery resolution, and configuration. |
| `contracts/chat/v2/` | Authoritative browser-to-BFF schemas for durable web chat, history, resumable events, reset, and commercial contact capture. |
| `contracts/chat/v1/` | Explicit compatibility schemas; not the current web-chat authority. |
| `compose.yml` | Site/BFF/Redis topology connected to the private agent service network. |
| `infrastructure/` | Host-managed Tunnel templates and site release verification. |
| `.codex/`, `.agents/skills/` | Scoped agents and reusable project skills. |
| `docs/discovery/` | Dated evidence snapshots and explicitly unknown external state. |
| `docs/quality/` | SEO, accessibility, and performance gates. |
| `docs/architecture/` | Technology, trust-boundary, and runtime decisions. |

The agent panel's configuration hierarchy, persistence ownership, write-only secret boundary, and channel routing are documented in [`agent-platform/docs/architecture/administration-model.md`](agent-platform/docs/architecture/administration-model.md). The landing workspace uses pnpm; the independent agent administration panel uses npm with its committed `package-lock.json`.

## Delivery rules

1. Keep changes in bounded work units and validate before a Conventional Commit.
2. Preserve public URLs, canonical intent, indexable content, contact paths, real 404 behavior, and structured data.
3. Measure preview and deployed responses before claiming ranking or performance improvements.
4. Never commit provider secrets or expose the agent directly to browser code.
5. Do not push, deploy, install services, change DNS, or mutate Cloudflare without explicit authorization.

Repository checks prove generated HTML, contracts, topology, and local behavior. Only deployed-response checks, provider evidence, Search Console, and field Core Web Vitals can prove production impact.
