# Self-hosted site infrastructure

This infrastructure unit deploys only the indexable landing, public BFF, and ephemeral rate-limit Redis. The repository-owned `agent-platform/` unit keeps its own API, panel, stores, migrations, and rollback lifecycle.

```text
Cloudflare Tunnel on the host
  /* -> 127.0.0.1:18080 -> frontend -> /api proxy -> backend
                                               |-> private Redis
                                               `-> agent-platform service bridge
```

There is no host Nginx or Caddy requirement. The agent panel container uses Nginx only as its internal static SPA server and API reverse proxy.

## Safety boundary

The templates contain no Tunnel UUID, credentials, provider secrets, DNS mutation, or proof of a live public route. Installing systemd units, changing Cloudflare, starting production, or promoting a release requires explicit operator authorization.

The BFF-to-agent bearer token and BFF session-signing secret are separate 32+ character files outside Git. Both are owned by the configured `SALTACODE_SECRET_GID`, use mode `0640` or `0440`, and are mounted read-only. Redis is digest-pinned, private, non-persistent, and fails chat closed when unavailable.

Cloudflare sends both the apex and `www` hostnames to the frontend origin. `/api` is deliberately **not** routed around the frontend: the browser and Tunnel use the same-origin frontend proxy, and the backend remains a separate loopback-only diagnostic origin. The frontend server provides a defensive `308` canonical-host/HTTPS fallback; an edge redirect rule remains valid defense in depth. Either way, direct path-and-query-preserving redirects must pass the public gate before cutover.

## Port and network allocation

Production and sandbox use independent loopback ports and non-overlapping Docker CIDRs:

| Environment | Frontend | Backend | frontend/backend | rate limit | ingress |
|---|---:|---:|---|---|---|
| production | `127.0.0.1:18080` | `127.0.0.1:18081` | `10.248.244.32/28` | `10.248.244.48/28` | `10.248.244.64/28` |
| sandbox | `127.0.0.1:28080` | `127.0.0.1:28081` | `10.248.242.32/28` | `10.248.242.48/28` | `10.248.242.64/28` |

The CIDRs are explicit environment values. Preflight validates their syntax, checks that the three site networks do not overlap, and rejects overlap with every Docker network except an unchanged network belonging to the same Compose project. This makes a normal redeploy idempotent without hiding contract drift.

## Files

- `../compose.yml`: site/BFF/Redis topology and private agent service bridge.
- `../compose.sandbox.yml`: local overlay.
- `env/*.example`: non-secret deployment interpolation.
- `cloudflare/*.example`: ordered host-managed Tunnel routes.
- `systemd/*.service`: host Tunnel unit templates.
- `scripts/deploy-site.sh`: bounded site-only release and rollback.
- `scripts/verify-local.sh`: origin, health, and local SEO checks.
- `scripts/verify-public.sh`: read-only public routing and SEO checks.

The independent agent unit is released with `agent-platform/scripts/platform/deploy-release.sh` and its own state directory, lock, migrations, health probes, receipts, and rollback script. See [`../agent-platform/docs/operations/release-and-rollback.md`](../agent-platform/docs/operations/release-and-rollback.md). Neither release script calls the other.

## Prepare

Copy an environment template outside Git, replace placeholders, and create the two protected secret files. The named `saltacode_agent_bridge` must already be created by the independently deployed agent platform.

Production release tags are immutable and identify both the clean Git revision and one release attempt:

```bash
printf 'git-%s-%s\n' "$(git rev-parse --short=12 HEAD)" "$(date -u +%Y%m%dT%H%M%SZ)"
```

Put that value in the external `SALTACODE_RELEASE`. Production preflight rejects a tag for another revision or a dirty worktree. Deployment also rejects a tag that already has a receipt or local frontend/backend image, so a failed attempt must use a new tag rather than rewriting image history.

```bash
SALTACODE_ENV_FILE=/etc/saltacode/production.env \
  infrastructure/scripts/preflight.sh /etc/saltacode/production.env site
```

Preflight checks Docker/Compose, Git/release identity, immutable Redis, service build inputs, loopback bindings, ports, Docker CIDR availability, private Redis URL, secret length/mode/group, production rate limiting, and the effective Compose model.

## Deploy and verify

```bash
SALTACODE_ENV_FILE=/etc/saltacode/production.env \
SALTACODE_STATE_DIR=/var/lib/saltacode \
  infrastructure/scripts/deploy-site.sh

infrastructure/scripts/verify-local.sh /etc/saltacode/production.env
SALTACODE_PUBLIC_BASE_URL=https://saltacode.com.ar \
  infrastructure/scripts/verify-public.sh
```

The deploy script builds locally, starts only Redis/backend/frontend with `--wait --no-build`, verifies the served result, records immutable release receipts, and rolls back only those site components after a failed promotion. Before promotion it proves that the prior frontend, backend, and Redis image IDs still exist and match the prior receipt. It never deploys or rolls back `agent-platform/`, removes volumes, changes the Tunnel, or alters DNS.

Every secret-free receipt records the full Git SHA, immutable release tag, effective Compose and allowlisted non-secret environment contract hashes, candidate image references and IDs, prior image IDs, timestamp, and environment. The receipt is mode `0440`, has a sibling SHA-256 checksum, and is selected through `current-site-receipt`. Neither secret contents, secret-derived hashes, nor provider credentials are recorded.

Local and public verifiers cover every indexable, contact, and legal route; canonicals; sitemap membership; robots; real 404 behavior; CSP and browser security headers; configured origin exposure; and a contract-only chat canary. The canary sends an intentionally unsupported privacy version, which the BFF rejects before rate limiting, session creation, persistence, or agent invocation. The public gate additionally requires one-year HSTS, direct path-and-query-preserving HTTP and `www` redirects, and an explicit release-verifier User-Agent.

These curl gates do **not** prove keyboard/screen-reader accessibility, Search Console state, rankings, or Core Web Vitals. Run the dedicated accessibility and performance gates separately and keep their evidence with the cutover record.

Do not cut over production until the exact immutable candidate passes loopback checks, canonical redirects, robots, sitemap, real 404 behavior, contact paths, performance gates, agent availability, and receipt-backed local rollback verification.
