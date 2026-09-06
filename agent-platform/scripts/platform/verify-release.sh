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
channel_inbound_worker_enabled="$(receipt_channel_inbound_worker_enabled "${release_receipt}")"
outbound_worker_enabled="$(receipt_outbound_worker_enabled "${release_receipt}")"
web_execution_worker_enabled="$(receipt_web_execution_worker_enabled "${release_receipt}")"
follow_up_worker_enabled="$(receipt_follow_up_worker_enabled "${release_receipt}")"
verify_release_runtime \
  "${RELEASE}" "${channel_inbound_worker_enabled}" \
  "${outbound_worker_enabled}" "${web_execution_worker_enabled}" \
  "${follow_up_worker_enabled}"
printf 'agent-platform release %s matches its receipt and is healthy on internal and loopback probes\n' \
  "${RELEASE}"
