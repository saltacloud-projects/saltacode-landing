# Technology direction: self-hosted static-first platform

Use Astro for the indexable landing surface, FastAPI for explicit HTTP boundaries, and locally built containers behind a host-managed Cloudflare Tunnel. This direction is implemented in the repository, but no production cutover or provider configuration is implied.

## Decisions

| Concern | Implemented direction |
|---|---|
| Frontend | Astro with strict TypeScript, pnpm, static output, and zero default client JavaScript. |
| Static origin | A small non-root Node server provides health, cache/security headers, and real 404 responses. |
| Public API | FastAPI with uv provides the same-origin BFF and versioned SSE chat boundary. |
| Private AI | A separate FastAPI/uv agent platform exposes an authenticated internal execution endpoint and owns multi-channel history, encrypted sources, tools, RAG, and provider adapters. |
| Contracts | Browser-facing schemas are versioned under `contracts/chat/v1/` and checked for drift. |
| Abuse control | A private, ephemeral Redis instance provides atomic shared rate limiting and fails closed. |
| Orchestration | Compose builds application images locally and isolates origin, agent, rate-limit, and egress networks. |
| Ingress | Host-managed `cloudflared` routes `/api/*` to the loopback BFF and other paths to the loopback static origin. |
| Proxy layer | No Nginx or Caddy. Add one only when measured requirements exceed the existing origins and Tunnel. |
| Deployment target | Self-hosted containers; Netlify and Cloudflare Pages are retired from this direction. |

## Why this fits

- The marketing surface is predominantly static, so pre-rendered HTML protects indexability and avoids hydration cost.
- The BFF keeps provider credentials, rate limiting, validation, and private-agent failures outside browser code.
- FastAPI matches the Python agent ecosystem and makes contracts easy to test. There is no measured bottleneck that justifies adding a second backend language.
- Separating the static origin, BFF, and agent allows independent release and rollback boundaries.
- Cloudflare Tunnel already provides public ingress, while both browser-facing origins remain loopback-only.

## Why there is no Nginx

The current static origin already serves immutable assets, revalidates HTML and crawl files, emits security headers, returns a real 404, and exposes a health endpoint. The FastAPI BFF owns API and SSE behavior, while `cloudflared` owns ordered public routing. An additional proxy would duplicate responsibilities without solving an evidenced problem.

Nginx or Caddy remains a valid future option if profiling proves a concrete need such as origin-level compression policy, advanced buffering control, or routing that the current boundary cannot express. That tradeoff would add another configuration, patching, observability, and rollback surface.

## AI integration state

The browser-to-BFF and BFF-to-agent boundaries exist, but the private agent intentionally returns unavailable until approved model, knowledge, and tool adapters are configured. Chat must remain outside the critical rendering path, keep a non-chat contact path available, and never send provider credentials to the browser.

## Production promotion gate

Before cutover:

1. Verify the existing host, DNS, Tunnel, redirects, cache rules, and rollback state read-only.
2. Validate generated metadata, schema, `robots.txt`, sitemap, links, contact paths, and real 404 behavior.
3. Run repeatable preview Lighthouse and accessibility checks against the quality contract.
4. Capture the current provider state and prove the apex/`www` policy and ordered `/api/*` route.
5. Promote only with explicit authorization, then verify deployed responses, Search Console, and field Core Web Vitals.

Passing repository or lab checks does not guarantee rankings. See [`platform-topology.md`](platform-topology.md) for runtime boundaries and [`../quality/seo-performance-contract.md`](../quality/seo-performance-contract.md) for release evidence.
