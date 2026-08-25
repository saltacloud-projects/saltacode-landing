# Self-hosted infrastructure

Saltacode runs as locally built application containers plus an immutable Redis rate limiter behind
a host-managed Cloudflare Tunnel:

```text
Cloudflare
  /api/*  -> 127.0.0.1:18081 -> FastAPI BFF -> agent-ai:8001
  /*      -> 127.0.0.1:18080 -> Astro static origin
                                   BFF -> redis:6379
```

The public BFF and static origin bind to loopback only. Each uses a dedicated origin bridge because
Docker port publishing requires north-south connectivity; those bridges do not expose any address
beyond the explicit `127.0.0.1` bindings. `agent-ai` has no host port and is reachable only from the
BFF over the private Compose network. The agent receives a separate egress network for provider
calls. Redis has no host port, joins only the BFF rate-limit network, and stores no durable data.
There is no Nginx, Caddy, database, or cloudflared sidecar in this initial topology.

All five networks use small, environment-configurable `/28` subnets. This avoids consuming Docker's
large automatic address pools on a host that runs many Compose projects. The production and sandbox
examples use distinct ranges; verify them against host routes and override them before startup if
the host or a VPN already routes `10.248.240.0/23`.

## Safety boundary

This directory is a sanitized scaffold. It does not contain a tunnel UUID, credentials file, token,
provider secret, DNS mutation, or proof that any public route is active. Installing units, copying
credentials, changing Cloudflare routes, and starting production remain separately authorized
operator actions.

Production requires `SALTACODE_RATE_LIMIT_BACKEND=redis`. The Redis container uses a digest-pinned
image supplied by `SALTACODE_REDIS_IMAGE`, no persistence, `noeviction`, a private internal network,
and no published port. Restarting it intentionally resets rate-limit windows. A Redis failure must
fail the public chat request closed rather than silently falling back to process memory.
Redis protected mode is disabled solely so the BFF can reach it across that isolated network; do
not attach the frontend, agent, Tunnel, or unrelated containers to `rate_limit`.

## Rate-limit identity

The BFF rate-limit key uses Cloudflare's `CF-Connecting-IP`, not the loopback socket address seen by
Uvicorn. That header is trusted only because port `18081` is published on `127.0.0.1` and the sole
public path is the host-managed Tunnel. Never bind the BFF to `0.0.0.0` or expose it directly: doing
so would let clients forge the header and bypass identity-based limits. Public verification must
confirm traffic still traverses Cloudflare before this trust rule is accepted.

## Files

- `../compose.yml`: hardened production topology.
- `../compose.sandbox.yml`: sandbox overlay; use the sandbox environment example so ports do not
  collide with production.
- `cloudflare/*.example`: locally managed Tunnel templates with ordered ingress rules.
- `systemd/*.service`: unit templates for a host-managed production or sandbox tunnel.
- `env/*.example`: non-secret deployment inputs.
- `scripts/deploy-site.sh`: release-tagged frontend and BFF deployment.
- `scripts/deploy-agent.sh`: independent agent deployment.
- `scripts/verify-local.sh`: loopback, health, and local SEO checks.
- `scripts/verify-public.sh`: read-only public SEO and routing checks.

## Prepare an environment

Create an operator-owned file outside the repository and restrict it to the deployment account:

```bash
sudo install -d -o saltacode -g saltacode -m 0750 /etc/saltacode /var/lib/saltacode
sudo install -o saltacode -g saltacode -m 0640 \
  infrastructure/env/production.env.example /etc/saltacode/production.env
```

Replace every placeholder and use a unique immutable `SALTACODE_RELEASE` for each deployment. The
environment file is used for Compose interpolation; it is not a secret store. Provider credentials
must be added only after their service contract exists and must remain outside Git.

Replace `SALTACODE_REDIS_IMAGE` with the inspected official-image reference including its real
`@sha256:` digest. `SALTACODE_REDIS_UID` and `SALTACODE_REDIS_GID` are part of that pinned image's
runtime contract and must be verified again when the digest changes. Preflight rejects a tag-only
or placeholder Redis reference.

Create one 32+ character bearer token file for BFF-to-agent authentication. Own it with a dedicated
host group, set mode `0640`, and put that group's numeric GID in
`SALTACODE_AGENT_INTERNAL_TOKEN_GID`. Compose mounts the same file read-only into both services and
adds only that supplemental group to their non-root processes, so the secret remains unreadable to
other host and container users. Neither service receives the value through Compose YAML or a
repository environment file. `preflight.sh` rejects a missing, short, incorrectly grouped, or
broadly readable file.

Sandbox uses both Compose files and its own project name and ports:

```bash
docker compose \
  --env-file infrastructure/env/sandbox.env.example \
  -f compose.yml -f compose.sandbox.yml config --quiet
```

The sandbox agent healthcheck uses `/health/live` because the sanitized seed deliberately returns
`503 not_ready` until real provider, knowledge, and tool adapters are configured. Production keeps
the stricter `/health/ready` gate; agent execution remains fail-closed in both environments.

### Temporary LAN preview

The frontend bind address defaults to `127.0.0.1`. To inspect the sandbox from a phone or tablet on
the same trusted LAN, override only the frontend address for that Compose invocation:

```bash
SALTACODE_FRONTEND_BIND_ADDRESS=0.0.0.0 docker compose \
  --env-file /path/to/sandbox.env \
  -f compose.yml -f compose.sandbox.yml \
  -p saltacode-sandbox up -d --no-deps frontend
```

Open `http://HOST_LAN_IP:28080`. The BFF remains bound to loopback and Redis/agent-ai keep no host
port. Direct HTTP previews omit the CSP HTTPS-upgrade directive so same-origin assets stay on the
LAN endpoint; HTTPS-forwarded production responses retain it. Do not use this override on an
untrusted network; recreate the frontend without it after the device review to restore the
loopback-only bind.

## Tunnel preparation

Copy the relevant template outside Git, insert the existing tunnel UUID and credentials path, then
validate it before installation:

```bash
cloudflared --config /etc/cloudflared/saltacode.yml tunnel ingress validate
cloudflared --config /etc/cloudflared/saltacode.yml tunnel ingress rule \
  https://saltacode.com.ar/api/v1/chat
cloudflared --config /etc/cloudflared/saltacode.yml tunnel ingress rule \
  https://saltacode.com.ar/
```

Ingress rules are evaluated top to bottom, so `/api/*` must remain before the frontend fallback.
The final catch-all intentionally returns 404. The `www` to apex redirect belongs in an explicitly
verified Cloudflare Redirect Rule; these templates do not claim or mutate that provider state.

Install exactly one tunnel unit only after the paths and service account are reviewed. Production
and sandbox templates intentionally use different configs and ports.

## Deploy and verify

The scripts require a pre-created state directory and acquire a shared `flock` lock. They build
locally, pull the digest-pinned Redis image, run `docker compose up --wait`, execute loopback/private
probes, and record the successful immutable application and Redis references. On a failed probe they
re-select the previously recorded references when they exist; they never remove volumes, run
`compose down`, change the Tunnel, or alter DNS.

```bash
SALTACODE_ENV_FILE=/etc/saltacode/production.env \
SALTACODE_STATE_DIR=/var/lib/saltacode \
  infrastructure/scripts/deploy-site.sh

SALTACODE_ENV_FILE=/etc/saltacode/production.env \
SALTACODE_STATE_DIR=/var/lib/saltacode \
  infrastructure/scripts/deploy-agent.sh

infrastructure/scripts/verify-local.sh /etc/saltacode/production.env
SALTACODE_PUBLIC_BASE_URL=https://saltacode.com.ar \
  infrastructure/scripts/verify-public.sh
```

Do not perform the origin cutover until the local checks, public preview, canonical redirect,
robots, sitemap, real 404 behavior, contact path, performance gates, and an external rollback probe
have all passed. A successful container healthcheck is not proof of public availability.

## Rollback

Each deploy script records the previous and current release under `SALTACODE_STATE_DIR`. Automatic
rollback is limited to the component deployed by that script:

- `deploy-site.sh`: `frontend`, `backend`, and ephemeral `redis`.
- `deploy-agent.sh`: `agent-ai` only.

Site receipts include `redis_image` and `previous_redis_image`; the current value is also stored in
`current-site-redis-image-release`. This preserves the exact digest needed by rollback rather than
re-resolving a mutable tag.

To roll back explicitly, set `SALTACODE_RELEASE` in a temporary protected environment file to the
recorded previous release and run only the matching services with `up -d --wait --no-deps`. Verify
locally and publicly afterward. Tunnel/DNS rollback is a separate provider operation and requires a
captured pre-cutover provider state; these scripts never guess it.
