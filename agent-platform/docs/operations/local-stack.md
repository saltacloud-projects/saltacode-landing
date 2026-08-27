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
docker compose --env-file .env.platform.local logs --tail=200 api panel
curl -fsS http://127.0.0.1:28082/ready
curl -fsS http://127.0.0.1:23000/
```

## Stop

```bash
./scripts/platform/down.sh
```

The normal stop command preserves named volumes. Volume deletion is intentionally not part of the standard workflow.

## Local access

The generated administrator email and temporary password live only in `.env.platform.local`. Rotate the password from the panel before using the stack outside a private development machine.

WhatsApp is disabled by default. Enabling it requires explicit Meta credentials, webhook configuration, signature verification, and an approved access policy.
