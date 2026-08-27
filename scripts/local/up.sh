#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
agent_root="${AGENT_PLATFORM_ROOT:-/data/ssd512/proyectos/agente-metalnor-worktrees/agent-platform}"
cd "$root"
./scripts/local/init.sh
"$agent_root/scripts/platform/up.sh"
docker compose --env-file .env.sandbox.local -f compose.yml -f compose.sandbox.yml up -d --build --remove-orphans --wait
./scripts/local/access.sh
