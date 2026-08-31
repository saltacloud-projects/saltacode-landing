# Rollback contract

Rollback is component-scoped and release-tagged. It never deletes volumes or images, changes DNS, edits Cloudflare, or runs `docker compose down`.

## Site rollback

Read the prior site receipt under `SALTACODE_STATE_DIR` and verify its checksum before touching containers:

```bash
state_dir=/var/lib/saltacode
receipt="$(cat "${state_dir}/current-site-receipt")"
(cd "$(dirname "${receipt}")" && sha256sum -c "$(basename "${receipt}").sha256")
```

Select the distinct `previous_release` and `previous_redis_image` from that receipt, then locate the receipt whose `release` equals that previous release. Verify that its `frontend_image_id`, `backend_image_id`, and `redis_image_id` still equal `docker image inspect --format '{{.Id}}'` for the corresponding references. A missing image, checksum mismatch, mutable tag, or receipt mismatch blocks application rollback.

Put the verified previous release and Redis digest in a protected environment file, then run only the site services without rebuilding:

```bash
docker compose --env-file /path/to/rollback.env -f compose.yml \
  up -d --wait --no-build --no-deps redis backend frontend
infrastructure/scripts/verify-local.sh /path/to/rollback.env
```

Only after verification passes, update `current-site-release`, `current-site-redis-image-release`, and `current-site-receipt` to the restored values using atomic files under `SALTACODE_STATE_DIR`. Keep the failed receipt; receipts are evidence and are never rewritten.

Redis is intentionally ephemeral, so rollback starts with empty public rate-limit windows. Agent conversations and sources are not stored in the site stack and are not changed.

The first self-hosted release has no prior local image receipt. Keep the Netlify origin and its provider configuration intact until the self-hosted candidate, preview, public cutover, and provider rollback have all been verified; do not describe an application rollback as available before that point.

## Agent rollback

Use the independent agent receipt and operation contract:

```bash
AGENT_PLATFORM_ENV_FILE=/etc/saltacode/agent-platform/production.env \
  agent-platform/scripts/platform/rollback-release.sh
```

The script validates immutable image IDs, Compose/environment hashes, and the current database revision before stopping the agent application. It never downgrades or restores PostgreSQL, deletes document/history volumes, rebuilds the landing, or changes DNS and Cloudflare. A database revision mismatch blocks rollback because restoring an older database would discard newer conversations. See [`../agent-platform/docs/operations/release-and-rollback.md`](../agent-platform/docs/operations/release-and-rollback.md).

## Provider rollback

Capture the current DNS, redirect, cache, Tunnel, canonical, robots, sitemap, representative indexed URLs, and external performance evidence before cutover. Provider restoration remains a separate authorized operation; this repository never guesses its target.
