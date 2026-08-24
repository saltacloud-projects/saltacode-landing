# Saltacode Platform

Saltacode's landing platform is now organized as a static-first Astro frontend, a public FastAPI BFF, a private AI-agent seed, versioned chat contracts, and self-hosted container infrastructure. This repository state is implemented and locally verifiable; it is **not** proof that production, DNS, Cloudflare Tunnel, Search Console, or field performance has changed.

## Quick validation

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm check
pnpm test

(cd backend && uv sync --locked --all-groups && uv run ruff format --check . \
  && uv run ruff check . && uv run pytest \
  && uv run python scripts/export_contracts.py --check)

(cd agent-ai && uv sync --locked --all-groups && uv run ruff format --check . \
  && uv run ruff check . && uv run pytest)

bash scripts/agentic/validate-layer.sh
```

Infrastructure model and release-candidate checks are documented in [`infrastructure/README.md`](infrastructure/README.md). They require operator-owned configuration outside Git and do not imply deployment authorization.

## Architecture at a glance

```text
Cloudflare Tunnel on the host
  /api/* -> loopback FastAPI BFF -> private agent-ai
                         |
                         +-> private ephemeral Redis rate limiter
  /*     -> loopback Astro static origin
```

- Netlify is retired as a target for this repository.
- Application images are built locally and orchestrated with Compose.
- `cloudflared` remains host-managed; there is no Nginx or Caddy layer.
- Marketing content is pre-rendered and indexable without client JavaScript.
- The chat boundary is implemented fail-closed; the private agent seed intentionally remains unavailable until provider, knowledge, and tool adapters are approved.

See [`docs/architecture/platform-topology.md`](docs/architecture/platform-topology.md) for trust boundaries and [`docs/architecture/technology-direction.md`](docs/architecture/technology-direction.md) for decisions and tradeoffs.

## Repository map

| Path | Purpose |
|---|---|
| `frontend/` | Astro, TypeScript, static SEO surface, optimized assets, and Node static origin. |
| `backend/` | Public FastAPI BFF, SSE chat contract, origin checks, correlation, and shared rate limiting. |
| `agent-ai/` | Private FastAPI orchestration seed derived from an allowlisted Metalnor baseline. |
| `contracts/chat/v1/` | Versioned browser-to-BFF JSON Schemas. |
| `compose.yml` | Hardened production topology; `compose.sandbox.yml` is its local overlay. |
| `infrastructure/` | Host-managed Tunnel templates, environment examples, verification, deployment, and rollback scripts. |
| `.codex/`, `.agents/skills/` | Scoped agents and reusable project skills. |
| `docs/discovery/` | Dated evidence snapshots and explicitly unknown external state. |
| `docs/quality/` | SEO, accessibility, and performance gates. |
| `docs/agentic/` | Tool availability and delivery workflow. |

## Delivery rules

1. Keep changes in bounded work units and validate each unit before a Conventional Commit.
2. Preserve public URLs, canonical intent, indexable content, contact paths, real 404 behavior, and structured data.
3. Measure preview and deployed responses before claiming SEO rankings or performance improvement.
4. Never commit provider secrets or expose the private agent to browsers.
5. Do not push, deploy, install services, change DNS, or mutate Cloudflare without explicit authorization.

## Recommended reading order

1. `docs/discovery/initial-baseline.md`
2. `docs/discovery/production-baseline.md`
3. `docs/quality/seo-performance-contract.md`
4. `docs/architecture/technology-direction.md`
5. `docs/architecture/platform-topology.md`
6. `docs/architecture/ai-chat-boundary.md`
7. `docs/agentic/tooling.md`

## Evidence boundary

Repository builds and tests can prove generated HTML, contracts, topology, and local behavior. Only deployed-response checks, provider evidence, Search Console, and field Core Web Vitals can prove production impact. Keep those facts unknown until they are measured.
