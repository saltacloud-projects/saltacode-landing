# Platform topology and trust boundaries

The site and the agent are independent Compose projects joined only through a named private bridge and a shared internal bearer token file. Cloudflare Tunnel remains a host-managed production concern.

## Request path

```text
Internet -> Cloudflare -> host cloudflared
  /* -> frontend:8080
          | static Astro assets
          ` /api/* proxy -> backend:8000
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
| Frontend proxy to BFF | Same-origin `/api/v1/chat`, bounded body, streamed response, forwarded cookie/origin/correlation only. |
| Browser contract at BFF | Exact-origin allowlist, versioned schema, explicit transcript consent, safe problem responses, rate limit, and signed HttpOnly session. |
| BFF to agent | Private named bridge, authenticated internal endpoint, file-mounted token, server-owned session identity, correlation propagation, and fail-closed errors. |
| BFF to Redis | Internal rate-limit network, atomic fixed-window decisions, no host port, no persistence, and fail-closed outage behavior. |
| Agent to sources | Source-bound allowlist, encrypted credentials, TLS, no redirects or ambient proxies, SSRF checks, bounded responses, channel/risk/confirmation/idempotency policy. |

## Runtime ownership

| Component | Owns | Does not own |
|---|---|---|
| `frontend` | Static files, cache/security headers, real 404, lazy chat client, same-origin API streaming proxy. | Session signing, provider keys, rate policy, agent tools. |
| `backend` | Browser validation, signed session, consent, origin policy, correlation, rate limit, and agent contract adaptation. | Marketing rendering, model execution, API source credentials. |
| `agent-platform/` service | Agents, principals, channel identities, histories, executions, encrypted sources, tools, WhatsApp adapter, RAG, and model/provider orchestration. | Direct public browser trust or landing rendering. |
| site Redis | Ephemeral public rate-limit counters. | Durable transcript or agent data. |
| agent PostgreSQL/Redis | Durable platform state and internal coordination. | Public ingress. |

## Network model

Published frontend and panel containers have a dedicated non-internal ingress bridge because Docker does not activate host port mappings for containers attached only to `internal: true` networks. All service-to-service data paths remain on internal or private bridges. Explicit `/28` subnets avoid exhausting Docker address pools on the multi-project host.

## Deployment boundary

The SaltaCode repository owns two independent release units. The site unit releases the frontend, BFF, and site Redis; `agent-platform/` releases its API, panel, database migrations, bootstrap, optional worker, and private stores. A site rollback must not reset agent history; an agent rollback must not rebuild the indexable landing.

Production, DNS, Cloudflare, Search Console, analytics, and field Core Web Vitals remain unknown until independently verified.
