#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

configure_environment "${1:-}"
acquire_deploy_lock
"${SCRIPT_DIR}/preflight.sh" "${ENV_FILE}" site

previous="$(read_previous_release site)"
previous_redis_image="$(read_previous_release site-redis-image)"
rollback() {
  local status=$?
  trap - ERR
  printf 'site deployment failed; attempting bounded rollback\n' >&2
  if [[ -n "${previous_redis_image}" ]]; then
    export SALTACODE_REDIS_IMAGE="${previous_redis_image}"
  fi
  if restore_release "${previous}" redis frontend backend; then
    atomic_write "${STATE_DIR}/current-site-release" "${previous}"
    if [[ -n "${previous_redis_image}" ]]; then
      atomic_write "${STATE_DIR}/current-site-redis-image-release" "${previous_redis_image}"
    fi
  fi
  exit "${status}"
}
trap rollback ERR

compose pull redis
compose build frontend backend
compose up -d --wait redis frontend backend
"${SCRIPT_DIR}/verify-local.sh" "${ENV_FILE}"
record_release site "${previous}" \
  "redis_image=${REDIS_IMAGE}" \
  "previous_redis_image=${previous_redis_image:-none}"
atomic_write "${STATE_DIR}/current-site-redis-image-release" "${REDIS_IMAGE}"

trap - ERR
printf 'site release %s deployed and verified locally; public state was not checked\n' "${RELEASE}"
