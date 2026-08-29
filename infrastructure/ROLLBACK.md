# Rollback contract

Rollback is component-scoped and release-tagged. It never deletes volumes or images, changes DNS, edits Cloudflare, or runs `docker compose down`.

## Site rollback

Read the prior site receipt under `SALTACODE_STATE_DIR`, put the previous release and Redis digest in a protected environment file, then run:

```bash
docker compose --env-file /path/to/rollback.env -f compose.yml \
  up -d --wait redis backend frontend
infrastructure/scripts/verify-local.sh /path/to/rollback.env
```

Redis is intentionally ephemeral, so rollback starts with empty public rate-limit windows. Agent conversations and sources are not stored in the site stack and are not changed.

## Agent rollback

Use the independent agent receipt and operation contract:

```bash
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  agent-platform/scripts/platform/rollback-release.sh
```

The script validates immutable image IDs, Compose/environment hashes, and the current database revision before stopping the agent application. It never downgrades or restores PostgreSQL, deletes document/history volumes, rebuilds the landing, or changes DNS and Cloudflare. A database revision mismatch blocks rollback because restoring an older database would discard newer conversations. See [`../agent-platform/docs/operations/release-and-rollback.md`](../agent-platform/docs/operations/release-and-rollback.md).

## Provider rollback

Capture the current DNS, redirect, cache, Tunnel, canonical, robots, sitemap, representative indexed URLs, and external performance evidence before cutover. Provider restoration remains a separate authorized operation; this repository never guesses its target.
