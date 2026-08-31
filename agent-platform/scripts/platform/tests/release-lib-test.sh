#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release-lib.sh
source "${SCRIPT_DIR}/../release-lib.sh"

test_root="$(mktemp -d)"
first_override="${test_root}/first-compose.yml"
second_override="${test_root}/second-compose.yml"
trap 'rm -rf -- "${test_root}"' EXIT

printf '%s\n' 'secrets: {}' >"${first_override}"
cp -- "${first_override}" "${second_override}"

first_hash="$(compose_contract_sha256 "${COMPOSE_FILE}" "${first_override}")"
second_hash="$(compose_contract_sha256 "${COMPOSE_FILE}" "${second_override}")"
[[ "${first_hash}" == "${second_hash}" ]] || {
  printf 'error: identical Compose content produced path-dependent hashes\n' >&2
  exit 1
}

printf '%s\n' 'services: {}' >>"${second_override}"
changed_hash="$(compose_contract_sha256 "${COMPOSE_FILE}" "${second_override}")"
[[ "${first_hash}" != "${changed_hash}" ]] || {
  printf 'error: changed Compose content did not change the contract hash\n' >&2
  exit 1
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

STATE_DIR="${test_root}/state"
RECEIPT_DIR="${STATE_DIR}/receipts"
ROLLBACK_RECEIPT_DIR="${STATE_DIR}/rollbacks"
# Consumed by atomic_write() from the sourced release library.
# shellcheck disable=SC2034
CURRENT_RELEASE_FILE="${STATE_DIR}/current-agent-platform-release"
mkdir -p "${RECEIPT_DIR}" "${ROLLBACK_RECEIPT_DIR}"
# Consumed by assert_release_restorable() from the sourced release library.
# shellcheck disable=SC2034
COMPOSE_CONTRACT_SHA256="compose-contract"
# shellcheck disable=SC2034
ENV_CONTRACT_SHA256="environment-contract"
# Consumed by record_deploy_receipt() from the sourced release library.
# shellcheck disable=SC2034
DEPLOY_ENV="sandbox"
# shellcheck disable=SC2034
RAG_WORKER_ENABLED="0"

cat >"${RECEIPT_DIR}/legacy-release.receipt" <<'EOF'
format_version=1
component=agent-platform
action=deploy
release=legacy-release
previous_release=none
compose_contract_sha256=compose-contract
environment_contract_sha256=environment-contract
database_revision_after=worker_revision
api_image_id=sha256:api-image
panel_image_id=sha256:panel-image
rag_worker_enabled=0
verification=passed
EOF

[[ "$(receipt_whatsapp_worker_enabled "${RECEIPT_DIR}/legacy-release.receipt")" == "0" ]] ||
  fail "version 1 receipt did not retain its pre-worker state"

image_id() {
  case "$1" in
    *-api:*) printf 'sha256:api-image' ;;
    *-panel:*) printf 'sha256:panel-image' ;;
    *) fail "unexpected image reference: $1" ;;
  esac
}

assert_release_restorable legacy-release worker_revision

# Consumed by record_deploy_receipt() from the sourced release library.
# shellcheck disable=SC2034
RELEASE="worker-release"
record_deploy_receipt legacy-release worker_revision worker_revision \
  sha256:api-image sha256:panel-image
worker_receipt="${RECEIPT_DIR}/worker-release.receipt"
[[ "$(receipt_value "${worker_receipt}" format_version)" == "2" ]] ||
  fail "new deploy receipt did not use format version 2"
[[ "$(receipt_whatsapp_worker_enabled "${worker_receipt}")" == "1" ]] ||
  fail "new deploy receipt did not require the WhatsApp worker"
[[ "$(receipt_value "${worker_receipt}" whatsapp_worker_image_id)" == \
   "$(receipt_value "${worker_receipt}" api_image_id)" ]] ||
  fail "new deploy receipt did not bind the WhatsApp worker to the API image"
assert_release_restorable worker-release worker_revision

invalid_receipt="${RECEIPT_DIR}/invalid-worker.receipt"
cp -- "${worker_receipt}" "${invalid_receipt}"
sed -i 's/^whatsapp_worker_image_id=.*/whatsapp_worker_image_id=sha256:other/' \
  "${invalid_receipt}"
if (receipt_whatsapp_worker_enabled "${invalid_receipt}" >/dev/null 2>&1); then
  fail "receipt accepted a WhatsApp worker image different from the API image"
fi

record_rollback_receipt current-release worker-release worker_revision
rollback_receipt="$(find "${ROLLBACK_RECEIPT_DIR}" -type f -name '*-to-worker-release.receipt')"
[[ "$(receipt_value "${rollback_receipt}" format_version)" == "2" ]] ||
  fail "rollback receipt did not use format version 2"
[[ "$(receipt_value "${rollback_receipt}" whatsapp_worker_enabled)" == "1" ]] ||
  fail "rollback receipt did not preserve the target WhatsApp worker state"
[[ "$(receipt_value "${rollback_receipt}" whatsapp_worker_image_id)" == "sha256:api-image" ]] ||
  fail "rollback receipt did not record the target WhatsApp worker image"

calls="${test_root}/compose-calls"
mock_worker_image_id="sha256:api-image"
compose_release() {
  local release="$1"
  shift
  printf '%s|%s\n' "${release}" "$*" >>"${calls}"
  case "$*" in
    "ps --status running --services")
      if [[ "${release}" == "legacy-release" ]]; then
        printf '%s\n' api panel
      else
        printf '%s\n' api panel whatsapp-worker
      fi
      ;;
    "ps -q whatsapp-worker")
      printf '%064d\n' 1
      ;;
  esac
}
docker() {
  [[ "$1" == "container" && "$2" == "inspect" && "$3" == "--format" ]] ||
    fail "unexpected docker command: $*"
  case "$4" in
    '{{.Config.Image}}') image_reference api worker-release ;;
    '{{.Image}}') printf '%s' "${mock_worker_image_id}" ;;
    *) fail "unexpected Docker inspect format: $4" ;;
  esac
}

: >"${calls}"
start_application_services legacy-release 0 0
! grep -Eq '^legacy-release\|up .* whatsapp-worker$' "${calls}" ||
  fail "version 1 lifecycle unexpectedly started the WhatsApp worker"
verify_whatsapp_worker_runtime legacy-release 0

: >"${calls}"
start_application_services worker-release 0 1
grep -Fq 'worker-release|up -d --wait --no-deps whatsapp-worker' "${calls}" ||
  fail "application start did not wait for the required WhatsApp worker healthcheck"
stop_application_services worker-release
grep -Fq 'worker-release|stop --timeout 30 panel rag-worker whatsapp-worker api' "${calls}" ||
  fail "application stop omitted the WhatsApp worker"
verify_whatsapp_worker_runtime worker-release 1

mock_worker_image_id="sha256:different-image"
if (verify_whatsapp_worker_runtime worker-release 1 >/dev/null 2>&1); then
  fail "runtime verification accepted a WhatsApp worker with the wrong image ID"
fi

printf 'release-lib contract, receipt, lifecycle, and WhatsApp worker tests passed\n'
