# Platform topology and trust boundaries

The platform uses two loopback origins behind a host-managed Cloudflare Tunnel. The AI service and Redis are private Compose services. No application or provider state has been deployed by creating this scaffold.

## Request paths

```text
Internet
  -> Cloudflare
    -> host cloudflared
      /api/* -> 127.0.0.1:18081 -> backend:8000
                                        |-> agent-ai:8001
                                        `-> redis:6379
      /*     -> 127.0.0.1:18080 -> frontend:8080
```

Ingress rules are ordered: `/api/*` must precede the frontend fallback, and the final Tunnel rule returns 404. The apex/`www` redirect remains a provider concern that must be inspected and tested before cutover.

## Trust boundaries

| Boundary | Contract |
|---|---|
| Browser to frontend | Static, indexable HTML; no provider secret and no required chat JavaScript. |
| Browser to BFF | Same-origin `/api/v1/chat`, exact-origin allowlist, versioned schema, SSE, safe problem responses, and no prompt persistence. |
| Tunnel to BFF | Loopback-only origin; validated `CF-Connecting-IP` is trusted only while Cloudflare is the sole public ingress. |
| BFF to agent | Private network, authenticated internal endpoint, file-mounted bearer token, correlation propagation, and fail-closed errors. |
| BFF to Redis | Private rate-limit network, atomic fixed-window decisions, no host port, no persistence, and fail-closed outage behavior. |
| Agent to providers | Separate egress network; provider, RAG, and tool adapters are not implemented in the seed. |

## Runtime responsibilities

| Component | Owns | Does not own |
|---|---|---|
| `cloudflared` on host | Public ingress and ordered path routing. | Static files, application auth, or chat business logic. |
| `frontend` | Static files, cache/security headers, health, and real 404 behavior. | API proxying or secrets. |
| `backend` | Public validation, origin policy, correlation, rate limiting, and SSE adaptation. | Model credentials in browser code or transcript storage. |
| `agent-ai` | Private orchestration ports and internal execution contract. | Public ingress; provider/RAG/tool behavior remains intentionally absent. |
| `redis` | Ephemeral shared rate-limit counters. | Durable application data or published access. |

## Deployment and rollback boundary

- `deploy-site.sh` owns the frontend, backend, and ephemeral Redis release.
- `deploy-agent.sh` owns the private agent release independently.
- The scripts build locally, verify health, and retain prior immutable references for component rollback.
- Tunnel, DNS, redirect, and external provider rollback remain separate operator actions.

Use [`../../infrastructure/README.md`](../../infrastructure/README.md) for sanitized preparation and verification commands. Starting containers, installing systemd units, changing Tunnel/DNS state, or promoting production requires explicit authorization.

## Evidence status

Repository tests can verify contracts, builds, Compose models, and local behavior. Current DNS, Tunnel ownership, provider configuration, deployed content, Search Console, analytics, rankings, and field Core Web Vitals remain unknown until inspected directly.
