# Agent platform release and rollback

The agent platform is an independent release unit. Its API, panel, required durable WhatsApp inbox worker, optional RAG worker, migrations, bootstrap, PostgreSQL, Redis, and document store are operated from `agent-platform/`; the landing release scripts never manage them.

## Safety contract

- A release tag is unique and immutable. Never use `dev`, `latest`, a branch name, or reuse an existing local image tag.
- Production uses an external mode-`0600` or `0640` environment file and protected secret files outside Git.
- The API and panel bind to `127.0.0.1` in production. Cloudflare Tunnel, DNS, and the landing are separate operations.
- PostgreSQL and document volumes are never deleted, recreated, downgraded, or restored by these scripts.
- Migrations run once, explicitly, while the old application processes are stopped. The deploy does not use `docker compose down`.
- The WhatsApp inbox worker is mandatory for every new release and runs from the exact immutable API image; it has no independently built image or release tag.
- Application rollback is permitted only when the current database revision, Compose contract, environment contract, and immutable image IDs match the target release receipt.
- If a migration changes the database revision, an automatic rollback to a release built for the old revision is blocked. Use a forward fix or perform a separately reviewed compatibility operation; restoring an old database would discard newer conversations and is intentionally outside this workflow.

## Host preparation

Create the state and secret directories once:

```bash
sudo install -d -m 0750 -o "$USER" -g saltacode /var/lib/saltacode-agent-platform
sudo install -d -m 0750 -o root -g saltacode /etc/saltacode/agent-platform
```

Prepare `/etc/saltacode/agent-platform/production.env` with mode `0640`. It contains Compose interpolation plus the script-only values below:

```dotenv
APP_VERSION=2026.08.29-REPLACE_WITH_GIT_SHA
AGENT_PLATFORM_DEPLOY_ENV=production
AGENT_PLATFORM_STATE_DIR=/var/lib/saltacode-agent-platform
AGENT_PLATFORM_INTERNAL_TOKEN_SOURCE_FILE=/etc/saltacode/secrets/agent-internal-token
AGENT_PLATFORM_SOURCE_MASTER_KEY_FILE=/etc/saltacode/secrets/agent-source-master-key
AGENT_PLATFORM_ENABLE_RAG_WORKER=0

FASTAPI_ENV=production
POSTGRES_DB=agent_platform
POSTGRES_USER=agent_platform
POSTGRES_PASSWORD=REPLACE_WITH_A_STRONG_SECRET
REDIS_MAX_MEMORY=256mb
JWT_SECRET_KEY=REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS
ADMIN_INITIAL_EMAIL=admin@example.com
ADMIN_INITIAL_PASSWORD=REPLACE_WITH_AT_LEAST_12_RANDOM_CHARACTERS
ADMIN_FRONTEND_URL=https://REPLACE_WITH_PANEL_ORIGIN
DEFAULT_AGENT_SLUG=saltacode
DOMAIN=REPLACE_WITH_AGENT_HOST
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
WHATSAPP_INBOX_WORKER_ID=whatsapp-inbox-worker-1
WHATSAPP_INBOX_POLL_SECONDS=1
WHATSAPP_INBOX_STALE_SECONDS=1200
WHATSAPP_INBOX_MAX_ATTEMPTS=5
AGENT_API_BIND_ADDRESS=127.0.0.1
AGENT_API_PORT=28082
AGENT_PANEL_BIND_ADDRESS=127.0.0.1
AGENT_PANEL_PORT=23000
```

The internal token file must contain the same value mounted into the landing BFF. The source master key is independent. Each must be a regular, non-symlink file with exactly one line and mode `0400`, `0440`, `0600`, or `0640`. Values never appear in receipts. Production also requires a real `DOMAIN`, an HTTPS `ADMIN_FRONTEND_URL` without a path, and loopback-only API and panel bindings.

The environment contract hash uses only an allowlist of non-secret runtime settings, including the WhatsApp worker identity, polling, stale-lease, and retry settings, and excludes `APP_VERSION`, allowing rollback between releases with otherwise identical behavior. Secret values are never written or hashed into receipts. Compose changes, secret-path changes, or non-secret operational configuration drift intentionally invalidate automatic rollback until compatibility is reviewed.

## Preflight

Preflight is read-only with respect to containers and persistent data:

```bash
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  agent-platform/scripts/platform/preflight-release.sh
```

It checks Docker/Compose capabilities, the clean production checkout, immutable release naming, loopback bindings, protected files, non-placeholder credentials, build inputs, effective image tags, and the rendered Compose model. The effective `whatsapp-worker` service must resolve to the same immutable API image reference.

## Deploy

Before authorizing a production release, run `pnpm verify` from the exact clean commit being tagged. The host preflight validates deployability; it does not replace the repository quality gate.

Production execution requires explicit operator authorization:

```bash
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  agent-platform/scripts/platform/deploy-release.sh
```

The bounded sequence is:

1. Acquire the agent-platform deployment lock.
2. Refuse reused receipts or image tags.
3. Build the API runtime and panel images locally.
4. Start and wait for PostgreSQL and Redis without replacing their volumes.
5. Record the current Alembic revision and stop only API, panel, the required WhatsApp worker, and optional RAG worker.
6. Run `alembic upgrade head` through the one-shot `migrate` service, then run bootstrap.
7. Start API, panel, and the required WhatsApp worker with `--no-deps`; start the RAG worker only when configured.
8. Verify API readiness inside the container and through loopback, panel HTTP inside the container and through loopback, and that the WhatsApp worker is running from the exact immutable API image reference and image ID.
9. Write a mode-`0640` receipt and atomically update the current release pointer.

A failure before cutover leaves the previous application running. A failure after cutover restores the previous application only when its receipt proves compatibility with the unchanged database. Persistent stores are always retained.

## Receipts

Deploy receipts live in:

```text
/var/lib/saltacode-agent-platform/receipts/<release>.receipt
```

Rollback audit receipts live under `rollbacks/`. Version 2 deploy and rollback receipts contain release identifiers, Git commit or rollback origin, contract hashes where applicable, database revisions, immutable API and panel image IDs, RAG state, required WhatsApp-worker state, verification state, and timestamps. The WhatsApp worker image ID must equal the API image ID. Receipts never contain environment values, passwords, provider keys, internal tokens, document contents, or conversation data. [`release-receipt.example`](release-receipt.example) remains the version 1 compatibility example.

Version 1 deploy receipts remain readable as historical releases with no WhatsApp worker. They are restorable only when the existing database, Compose contract, environment contract, and immutable API/panel image IDs still match. Because adding the worker changes the Compose contract and its migration advances the database revision, a pre-worker release is normally and intentionally blocked from automatic rollback after this cutover.

## Rollback

Rollback defaults to the previous release recorded by the current deploy receipt:

```bash
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  agent-platform/scripts/platform/rollback-release.sh
```

An explicit compatible target can be supplied as the second argument:

```bash
agent-platform/scripts/platform/rollback-release.sh \
  /etc/saltacode/agent-platform/production.env \
  2026.08.29-REPLACE_WITH_PRIOR_GIT_SHA
```

Rollback verifies both releases before stopping anything, never runs migrations or bootstrap, restores the target API, panel, required WhatsApp worker, and optional RAG worker according to the target receipt, verifies them, records the operation, and updates the pointer. On a failed target start it attempts to restore the release that was current when rollback began, including its recorded worker state.

## Verification only

To verify that the recorded release still matches its immutable receipt, current database revision, image IDs, and internal and loopback probes without deploying:

```bash
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  agent-platform/scripts/platform/verify-release.sh
```

None of these scripts change DNS, Cloudflare Tunnel, host services, or the landing stack.

After a compatible release is verified, use the [WhatsApp Cloud API onboarding runbook](whatsapp-onboarding.md) to create the persisted connection and route, run the real Meta canary, and retain rollback evidence.
