#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release-lib.sh
source "${SCRIPT_DIR}/release-lib.sh"

configure_release_environment "${1:-}"
acquire_release_lock
"${SCRIPT_DIR}/preflight-release.sh" "${ENV_FILE}"

from_release="$(current_release)"
[[ -n "${from_release}" ]] || die "no current agent-platform release is recorded"
from_receipt="$(deploy_receipt_path "${from_release}")"
[[ -r "${from_receipt}" ]] || die "current release receipt is missing: ${from_receipt}"

target_release="${2:-}"
if [[ -z "${target_release}" ]]; then
  target_release="$(receipt_value "${from_receipt}" previous_release)"
fi
valid_release_tag "${target_release}" || die "a valid target release is required"
[[ "${target_release}" != "${from_release}" ]] || die "target release is already current"

compose_release "${from_release}" up -d --wait postgres redis
current_database_revision="$(database_revision "${from_release}")"
assert_release_restorable "${from_release}" "${current_database_revision}"
assert_release_restorable "${target_release}" "${current_database_revision}"
target_receipt="$(deploy_receipt_path "${target_release}")"
target_rag="$(receipt_value "${target_receipt}" rag_worker_enabled)"
from_rag="$(receipt_value "${from_receipt}" rag_worker_enabled)"
target_whatsapp="$(receipt_whatsapp_worker_enabled "${target_receipt}")"
from_whatsapp="$(receipt_whatsapp_worker_enabled "${from_receipt}")"

restore_current_after_failure() {
  local status=$?
  trap - ERR
  printf 'agent-platform rollback failed; attempting to restore release %s\n' "${from_release}" >&2
  stop_application_services "${target_release}" || true
  if start_application_services "${from_release}" "${from_rag}" "${from_whatsapp}" &&
     verify_release_runtime "${from_release}" "${from_whatsapp}"; then
    printf 'release %s was restored; persistent stores were untouched\n' "${from_release}" >&2
  fi
  exit "${status}"
}
trap restore_current_after_failure ERR

stop_application_services "${from_release}"
start_application_services "${target_release}" "${target_rag}" "${target_whatsapp}"
verify_release_runtime "${target_release}" "${target_whatsapp}"
record_rollback_receipt "${from_release}" "${target_release}" "${current_database_revision}"
trap - ERR

printf 'agent-platform rolled back from %s to %s; database, documents, histories, landing, DNS, and Tunnel were untouched\n' \
  "${from_release}" "${target_release}"
