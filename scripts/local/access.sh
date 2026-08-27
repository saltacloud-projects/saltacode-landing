#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
agent_root="${AGENT_PLATFORM_ROOT:-/data/ssd512/proyectos/agente-metalnor-worktrees/agent-platform}"
lan_ip="$(hostname -I | awk '{print $1}')"
admin_email="$(sed -n 's/^ADMIN_INITIAL_EMAIL=//p' "$agent_root/.env.platform.local")"

cat <<ACCESS
Local access:
  Landing + web chat: http://${lan_ip}:28080
  SaltaCode BFF docs: http://${lan_ip}:28081/docs
  Agent API docs:     http://${lan_ip}:28082/docs
  Agent panel:        http://${lan_ip}:23000
  Panel user:         ${admin_email}

Read the generated local panel password with:
  sed -n 's/^ADMIN_INITIAL_PASSWORD=//p' ${agent_root}/.env.platform.local
ACCESS
