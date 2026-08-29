#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release-lib.sh
source "${SCRIPT_DIR}/release-lib.sh"

configure_release_environment "${1:-}"
acquire_release_lock
"${SCRIPT_DIR}/preflight-release.sh" "${ENV_FILE}"

previous_release="$(current_release)"
[[ "${previous_release}" != "${RELEASE}" ]] || die "release ${RELEASE} is already current"
[[ ! -e "$(deploy_receipt_path "${RELEASE}")" ]] ||
  die "release ${RELEASE} already has an immutable receipt"

api_image="$(image_reference api "${RELEASE}")"
panel_image="$(image_reference panel "${RELEASE}")"
if docker image inspect "${api_image}" >/dev/null 2>&1 ||
   docker image inspect "${panel_image}" >/dev/null 2>&1; then
  die "release image tags already exist; choose a new immutable APP_VERSION"
fi

compose_release "${RELEASE}" build api panel
api_image_id="$(image_id "${api_image}")"
panel_image_id="$(image_id "${panel_image}")"

compose_release "${RELEASE}" up -d --wait postgres redis
database_before="$(database_revision "${RELEASE}")"
cutover_started=0
database_after="${database_before}"

restore_previous_after_failure() {
  local status=$?
  trap - ERR
  printf 'agent-platform deployment failed\n' >&2
  if [[ "${cutover_started}" == "1" ]]; then
    stop_application_services "${RELEASE}" || true
    database_after="$(database_revision "${RELEASE}" 2>/dev/null || printf unknown)"
    if [[ -n "${previous_release}" && "${database_after}" == "${database_before}" ]]; then
      if assert_release_restorable "${previous_release}" "${database_after}"; then
        previous_receipt="$(deploy_receipt_path "${previous_release}")"
        previous_rag="$(receipt_value "${previous_receipt}" rag_worker_enabled)"
        if start_application_services "${previous_release}" "${previous_rag}" &&
           verify_release_runtime "${previous_release}"; then
          printf 'previous release %s was restored; persistent stores were untouched\n' \
            "${previous_release}" >&2
        fi
      fi
    else
      printf 'automatic application rollback is blocked because the database revision changed; persistent stores remain untouched\n' >&2
    fi
  fi
  exit "${status}"
}
trap restore_previous_after_failure ERR

cutover_started=1
stop_application_services "${RELEASE}"
compose_release "${RELEASE}" run --rm --no-deps migrate
database_after="$(database_revision "${RELEASE}")"
compose_release "${RELEASE}" run --rm --no-deps bootstrap
start_application_services "${RELEASE}" "${RAG_WORKER_ENABLED}"
verify_release_runtime "${RELEASE}"

record_deploy_receipt "${previous_release}" "${database_before}" "${database_after}" \
  "${api_image_id}" "${panel_image_id}"
trap - ERR

printf 'agent-platform release %s deployed and verified; landing, DNS, and Tunnel were untouched\n' \
  "${RELEASE}"
