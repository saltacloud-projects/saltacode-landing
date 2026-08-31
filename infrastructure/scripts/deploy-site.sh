#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

configure_environment "${1:-}"
acquire_deploy_lock
"${SCRIPT_DIR}/preflight.sh" "${ENV_FILE}" site
assert_release_identity

previous="$(read_previous_release site)"
previous_redis_image="$(read_previous_release site-redis-image)"
assert_site_release_tag_available
assert_site_restore_point "${previous}" "${previous_redis_image}"
compose_contract_sha256="$(compose_contract_hash)"
environment_contract_sha256="$(environment_contract_hash)"
promotion_started=0
rollback() {
  local status=$?
  trap - ERR
  if (( promotion_started == 0 )); then
    printf 'site release preparation failed before promotion; existing services were not changed\n' >&2
    exit "${status}"
  fi
  printf 'site deployment failed; attempting bounded rollback\n' >&2
  if [[ -n "${previous_redis_image}" ]]; then
    export SALTACODE_REDIS_IMAGE="${previous_redis_image}"
  fi
  if restore_release "${previous}" redis backend frontend &&
     [[ "$(running_service_image_id frontend)" == "${PREVIOUS_FRONTEND_IMAGE_ID}" ]] &&
     [[ "$(running_service_image_id backend)" == "${PREVIOUS_BACKEND_IMAGE_ID}" ]] &&
     [[ "$(running_service_image_id redis)" == "${PREVIOUS_REDIS_IMAGE_ID}" ]]; then
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
frontend_image_id="$(image_id "localhost/saltacode/frontend:${RELEASE}")"
backend_image_id="$(image_id "localhost/saltacode/backend:${RELEASE}")"
redis_image_id="$(image_id "${REDIS_IMAGE}")"
[[ -n "${frontend_image_id}" && -n "${backend_image_id}" && -n "${redis_image_id}" ]] ||
  die "candidate image identities could not be resolved"

promotion_started=1
compose up -d --wait --no-build redis backend frontend
[[ "$(running_service_image_id frontend)" == "${frontend_image_id}" ]] ||
  die "running frontend image does not match the candidate receipt"
[[ "$(running_service_image_id backend)" == "${backend_image_id}" ]] ||
  die "running backend image does not match the candidate receipt"
[[ "$(running_service_image_id redis)" == "${redis_image_id}" ]] ||
  die "running Redis image does not match the candidate receipt"
"${SCRIPT_DIR}/verify-local.sh" "${ENV_FILE}"
record_release site "${previous}" \
  "git_sha=${RELEASE_GIT_SHA}" \
  "compose_contract_sha256=${compose_contract_sha256}" \
  "environment_contract_sha256=${environment_contract_sha256}" \
  "frontend_image=localhost/saltacode/frontend:${RELEASE}" \
  "frontend_image_id=${frontend_image_id}" \
  "backend_image=localhost/saltacode/backend:${RELEASE}" \
  "backend_image_id=${backend_image_id}" \
  "redis_image=${REDIS_IMAGE}" \
  "redis_image_id=${redis_image_id}" \
  "previous_frontend_image_id=${PREVIOUS_FRONTEND_IMAGE_ID}" \
  "previous_backend_image_id=${PREVIOUS_BACKEND_IMAGE_ID}" \
  "previous_redis_image=${previous_redis_image:-none}" \
  "previous_redis_image_id=${PREVIOUS_REDIS_IMAGE_ID}"
atomic_write "${STATE_DIR}/current-site-redis-image-release" "${REDIS_IMAGE}"

trap - ERR
printf 'site release %s deployed and verified locally; receipt=%s; public state was not checked\n' \
  "${RELEASE}" "${LAST_RELEASE_RECEIPT}"
