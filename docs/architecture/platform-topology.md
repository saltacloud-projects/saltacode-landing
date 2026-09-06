# Platform topology and trust boundaries

The public site and Agent Platform are independent Compose release units joined only through a named private bridge and a shared internal bearer token file. Cloudflare Tunnel remains a host-managed production concern.

## Request path

```text
Internet -> Cloudflare -> host cloudflared
  /* -> frontend:8080
          | static Astro assets
          ` /api/* proxy -> backend:8000 (apps/web-bff/)
                                |-> redis:6379
                                `-> agent-platform:8000
                                         |-> PostgreSQL
                                         |-> agent Redis
                                         `-> approved providers and API sources
```

The frontend same-origin proxy prevents browser CORS coupling and streams SSE without buffering. The BFF is still the public security boundary; the agent API is never a browser target.

## Trust boundaries

| Boundary | Contract |
|---|---|
| Browser to frontend | Static, indexable HTML; lazy chat code; no provider or agent secret. |
| Landing proxy to BFF | Same-origin `/api/v2/chat/*` plus retained explicit compatibility routes, bounded bodies, streamed responses, and forwarded cookie/origin/correlation only. |
| Browser contract at BFF | Exact-origin allowlist, versioned schemas, explicit transcript and commercial-contact consent, safe problem responses, rate limit, and signed HttpOnly session. |
| BFF to agent | Private named bridge, authenticated internal endpoint, file-mounted token, server-owned session identity, correlation propagation, and fail-closed errors. |
| BFF to Redis | Internal rate-limit network, atomic fixed-window decisions, no host port, no persistence, and fail-closed outage behavior. |
| Agent to sources | Source-bound allowlist, encrypted credentials, TLS, no redirects or ambient proxies, SSRF checks, bounded responses, channel/risk/confirmation/idempotency policy. |

## Runtime ownership

| Component | Owns | Does not own |
|---|---|---|
| `apps/landing/` (`frontend` service) | Static files, cache/security headers, real 404, lazy chat client, and same-origin API streaming proxy. | Session signing, provider keys, rate policy, agent tools. |
| `apps/web-bff/` (`backend` service) | Browser validation, signed session, consent, origin policy, correlation, rate limit, and private Agent Platform contract adaptation. | Marketing rendering, model execution, commercial persistence, or API source credentials. |
| `agent-platform/api/` | Agents, principals, channel identities, histories, executions, commercial state, human control, encrypted sources, tools, WhatsApp adapter, RAG, and model/provider orchestration. | Direct public browser trust or landing rendering. |
| `agent-platform/panel/` | Authenticated administration UI scoped by platform and selected-agent grants. | Browser-held provider credentials or authorization by visual selection alone. |
| site Redis | Ephemeral public rate-limit counters. | Durable transcript or agent data. |
| agent PostgreSQL/Redis | Durable platform state and internal coordination. | Public ingress. |

## Administration ownership

The agent control plane follows `platform -> shared connection/resource libraries -> selected agent`. Provider and channel connections, integration sources, tools, knowledge blocks, document areas, and reusable WhatsApp identities are defined once. Explicit bindings assign the allowed subset to each agent together with its runtime, routes, access policy, conversations, and PromptLab context.

The implementation and activation state of human control, identity linking, opportunities, durable outbound, channel adapters, and external integrations is tracked in [`human-led-omnichannel-sales.md`](./human-led-omnichannel-sales.md). Repository implementation is not proof that a provider route or production release is active.

Web routing is server-owned: the BFF sends its configured `SALTACODE_AGENT_ROUTE_KEY`, and the agent platform resolves the persisted public web route. WhatsApp uses `GET|POST /webhooks/whatsapp/{route_key}` to resolve the persisted channel route and connection, validates the signature and external account, and only then resolves provider runtime for a processable message. New routed audit records persist agent and channel-route ownership, and both the administration API and selected-agent panel require that scope. Historical records without trustworthy ownership remain stored with `NULL` scope and are excluded from agent views rather than attributed by inference.

The detailed persistence and secret map lives in [`../../agent-platform/docs/architecture/administration-model.md`](../../agent-platform/docs/architecture/administration-model.md).

## Network model

Published frontend and panel containers have a dedicated non-internal ingress bridge because Docker does not activate host port mappings for containers attached only to `internal: true` networks. All service-to-service data paths remain on internal or private bridges. Explicit `/28` subnets avoid exhausting Docker address pools on the multi-project host.

## Deployment boundary

The SaltaCode repository owns two independent release units. The site unit releases the frontend, BFF, and site Redis; `agent-platform/` releases its API, panel, database migrations, bootstrap, optional worker, and private stores. A site rollback must not reset agent history; an agent rollback must not rebuild the indexable landing.

Production, DNS, Cloudflare, Search Console, analytics, and field Core Web Vitals remain unknown until independently verified.
