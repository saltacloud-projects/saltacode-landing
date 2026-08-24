# Rollback contract

Rollback is component-scoped and release-tagged. It never removes volumes, deletes images, changes
DNS, edits Cloudflare state, or runs `docker compose down`.

## Before cutover

Capture outside Git:

1. Current Cloudflare DNS, redirect, cache, and Tunnel route state.
2. Current public response headers, canonical, robots, sitemap, and representative URLs.
3. The last verified site and agent release tags plus the exact Redis image digest.
4. The exact operator and command authorized to restore the previous origin.

Without those receipts, Tunnel or DNS rollback is unknown and the production cutover must stop.

## Site rollback

Read `current-site-release` and the preceding site receipt from `SALTACODE_STATE_DIR`. Put the
previous release and Redis digest in a protected temporary environment file, then run:

```bash
docker compose --env-file /path/to/rollback.env -f compose.yml \
  up -d --wait redis frontend backend
infrastructure/scripts/verify-local.sh /path/to/rollback.env
```

Run `verify-public.sh` only after the authorized provider route targets this origin.
Redis is intentionally ephemeral, so rollback starts with empty rate-limit windows; no application
or transcript data is stored in it.

## Agent rollback

Use the prior agent receipt and change only `agent-ai`:

```bash
docker compose --env-file /path/to/rollback.env -f compose.yml \
  up -d --wait --no-deps agent-ai
```

Verify its container health and the BFF-to-agent private request. A successful agent rollback must
not restart the static site or mutate Cloudflare.

## Provider rollback

Restoring Netlify is not assumed. The provider rollback target must be captured and approved before
the origin cutover. After restoring it, verify the apex response, direct `www` redirect, canonical,
robots, sitemap, contact path, representative indexed URLs, and external performance evidence.
