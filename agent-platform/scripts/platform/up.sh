#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
./scripts/platform/init-local-secrets.sh
docker compose --env-file .env.platform.local up -d --build --wait
