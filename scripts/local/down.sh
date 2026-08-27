#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
agent_root="${root}/agent-platform"
cd "$root"
docker compose --env-file .env.sandbox.local -f compose.yml -f compose.sandbox.yml down
"$agent_root/scripts/platform/down.sh"
