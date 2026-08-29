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

```bash
SALTACODE_ENV_FILE=/etc/saltacode/production.env \
  infrastructure/scripts/preflight.sh /etc/saltacode/production.env site
```

Preflight checks Docker/Compose, immutable Redis, service build inputs, private Redis URL, secret length/mode/group, production rate limiting, and the effective Compose model.

## Deploy and verify

```bash
SALTACODE_ENV_FILE=/etc/saltacode/production.env \
SALTACODE_STATE_DIR=/var/lib/saltacode \
  infrastructure/scripts/deploy-site.sh

infrastructure/scripts/verify-local.sh /etc/saltacode/production.env
SALTACODE_PUBLIC_BASE_URL=https://saltacode.com.ar \
  infrastructure/scripts/verify-public.sh
```

The deploy script builds locally, starts only Redis/frontend/backend with `--wait`, verifies the served result, records immutable release receipts, and rolls back only those site components after a failed probe. It never deploys or rolls back `agent-platform/`, removes volumes, changes the Tunnel, or alters DNS.

Do not cut over production until local checks, an authorized public preview, canonical redirects, robots, sitemap, real 404 behavior, contact paths, performance gates, agent availability, and external rollback evidence all pass.
