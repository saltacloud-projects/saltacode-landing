#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release-lib.sh
source "${SCRIPT_DIR}/release-lib.sh"

configure_release_environment "${1:-}"
recorded_release="$(current_release)"
[[ "${recorded_release}" == "${RELEASE}" ]] ||
  die "APP_VERSION ${RELEASE} is not the recorded current release ${recorded_release:-none}"
current_database_revision="$(database_revision "${RELEASE}")"
assert_release_restorable "${RELEASE}" "${current_database_revision}"
release_receipt="$(deploy_receipt_path "${RELEASE}")"
whatsapp_worker_enabled="$(receipt_whatsapp_worker_enabled "${release_receipt}")"
verify_release_runtime "${RELEASE}" "${whatsapp_worker_enabled}"
printf 'agent-platform release %s matches its receipt and is healthy on internal and loopback probes\n' \
  "${RELEASE}"
