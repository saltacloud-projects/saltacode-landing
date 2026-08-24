#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

configure_environment "${1:-}"
acquire_deploy_lock
"${SCRIPT_DIR}/preflight.sh" "${ENV_FILE}" agent

previous="$(read_previous_release agent)"
rollback() {
  local status=$?
  trap - ERR
  printf 'agent deployment failed; attempting bounded rollback\n' >&2
  restore_release "${previous}" agent-ai || true
  exit "${status}"
}
trap rollback ERR

compose build agent-ai
compose up -d --wait --no-deps agent-ai
compose exec -T agent-ai python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/ready', timeout=3)"
if compose ps --status running --services | grep -qx backend; then
  compose exec -T backend python -c \
    "import urllib.request; urllib.request.urlopen('http://agent-ai:8001/health/ready', timeout=3)"
fi
record_release agent "${previous}"

trap - ERR
printf 'agent release %s deployed and verified privately; public state was not checked\n' "${RELEASE}"
