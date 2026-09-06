# Local stack operations

## Start

```bash
./scripts/platform/init-local-secrets.sh
./scripts/platform/up.sh
```

The scripts create ignored local secrets, the isolated databases and networks, apply the clean platform migration, bootstrap the initial administrator and default agent, then wait for readiness.

## Inspect

```bash
docker compose --env-file .env.platform.local ps -a
docker compose --env-file .env.platform.local logs --tail=200 \
  api panel whatsapp-worker outbound-worker web-execution-worker follow-up-worker
curl -fsS http://127.0.0.1:28082/ready
curl -fsS http://127.0.0.1:23000/
```

## Stop

```bash
./scripts/platform/down.sh
```

The normal stop command preserves named volumes. Volume deletion is intentionally not part of the standard workflow.

## Local access

The generated administrator email and temporary password live only in `.env.platform.local`. Rotate the password from the panel before using the stack outside a private development machine. Source, contact-encryption, and contact-lookup key files are generated independently under `.secrets/` with mode `0400`; losing them can make encrypted configuration or contact data unavailable.

`whatsapp-worker` is the Compose compatibility name for the required provider-neutral channel-inbound worker. Its wrapper executes `app.workers.channel_inbound` and can run without an active route. Only WhatsApp currently has an executable adapter; real WhatsApp processing remains unavailable until Meta credentials, webhook configuration, signature verification, access policy, and a real canary are complete. Catalog entries for other channels do not make them executable.

The outbound, web-execution, and follow-up workers are also required. The follow-up worker can run before a delivery provider is ready: it revalidates persisted ownership, control, consent, contact, route, and policy, then writes delivery intent for the outbound worker instead of calling a provider directly. The optional RAG worker is the only worker omitted when its feature is disabled.
