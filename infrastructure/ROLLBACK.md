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

Use the agent repository's own release receipt and operation contract. An agent rollback must preserve its database and history, restore the authenticated internal execution contract, and must not rebuild the landing or change Cloudflare.

## Provider rollback

Capture the current DNS, redirect, cache, Tunnel, canonical, robots, sitemap, representative indexed URLs, and external performance evidence before cutover. Provider restoration remains a separate authorized operation; this repository never guesses its target.
