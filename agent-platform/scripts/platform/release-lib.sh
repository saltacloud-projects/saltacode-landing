#!/usr/bin/env bash

set -Eeuo pipefail

PLATFORM_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${PLATFORM_ROOT}/docker-compose.yml"
COMPOSE_OVERRIDE_FILE=""

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

env_value() {
  local key="$1"
  local file="$2"

  awk -v wanted="${key}" '
    /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
    {
      line = $0
      sub(/^[[:space:]]*export[[:space:]]+/, "", line)
      name = line
      sub(/=.*/, "", name)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (name == wanted) {
        sub(/^[^=]*=/, "", line)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
        if ((substr(line, 1, 1) == "\"" && substr(line, length(line), 1) == "\"") ||
            (substr(line, 1, 1) == "\047" && substr(line, length(line), 1) == "\047")) {
          line = substr(line, 2, length(line) - 2)
        }
        print line
        exit
      }
    }
  ' "${file}"
}

effective_env_value() {
  local key="$1"
  local file="$2"
  if [[ -v "${key}" ]]; then
    printf '%s' "${!key}"
  else
    env_value "${key}" "${file}"
  fi
}

compatible_env_value() {
  local canonical_key="$1"
  local legacy_key="$2"
  local default_value="$3"
  local file="$4"
  local canonical_value legacy_value
  canonical_value="$(effective_env_value "${canonical_key}" "${file}")"
  legacy_value="$(effective_env_value "${legacy_key}" "${file}")"
  if [[ -n "${canonical_value}" && -n "${legacy_value}" &&
        "${canonical_value}" != "${legacy_value}" ]]; then
    die "${canonical_key} and ${legacy_key} must have the same value during the compatibility window"
  fi
  printf '%s' "${canonical_value:-${legacy_value:-${default_value}}}"
}

compose_contract_sha256() {
  local compose_file="$1"
  local override_file="$2"
  {
    printf 'compose=%s\n' "$(sha256sum <"${compose_file}" | awk '{print $1}')"
    printf 'override=%s\n' "$(sha256sum <"${override_file}" | awk '{print $1}')"
  } | sha256sum | awk '{print $1}'
}

cleanup_release_files() {
  if [[ -n "${COMPOSE_OVERRIDE_FILE}" ]]; then
    rm -f -- "${COMPOSE_OVERRIDE_FILE}"
  fi
}

valid_release_tag() {
  local value="$1"
  local lower="${value,,}"
  [[ "${value}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || return 1
  case "${lower}" in
    dev|latest|main|master|none|*replace*|*example*) return 1 ;;
  esac
}

configure_release_environment() {
  ENV_FILE="${AGENT_PLATFORM_ENV_FILE:-${1:-}}"
  [[ -n "${ENV_FILE}" ]] || die "set AGENT_PLATFORM_ENV_FILE or pass an environment file"
  [[ -r "${ENV_FILE}" ]] || die "environment file is not readable: ${ENV_FILE}"

  DEPLOY_ENV="${AGENT_PLATFORM_DEPLOY_ENV:-$(env_value AGENT_PLATFORM_DEPLOY_ENV "${ENV_FILE}")}"
  DEPLOY_ENV="${DEPLOY_ENV:-production}"
  [[ "${DEPLOY_ENV}" == "production" || "${DEPLOY_ENV}" == "sandbox" ]] ||
    die "AGENT_PLATFORM_DEPLOY_ENV must be production or sandbox"

  RELEASE="${AGENT_PLATFORM_RELEASE:-$(effective_env_value APP_VERSION "${ENV_FILE}")}"
  valid_release_tag "${RELEASE}" || die "APP_VERSION must be a unique immutable release tag"

  POSTGRES_DB_VALUE="$(effective_env_value POSTGRES_DB "${ENV_FILE}")"
  POSTGRES_USER_VALUE="$(effective_env_value POSTGRES_USER "${ENV_FILE}")"
  API_BIND_ADDRESS="$(effective_env_value AGENT_API_BIND_ADDRESS "${ENV_FILE}")"
  API_BIND_ADDRESS="${API_BIND_ADDRESS:-127.0.0.1}"
  API_PORT="$(effective_env_value AGENT_API_PORT "${ENV_FILE}")"
  API_PORT="${API_PORT:-28082}"
  PANEL_BIND_ADDRESS="$(effective_env_value AGENT_PANEL_BIND_ADDRESS "${ENV_FILE}")"
  PANEL_BIND_ADDRESS="${PANEL_BIND_ADDRESS:-127.0.0.1}"
  PANEL_PORT="$(effective_env_value AGENT_PANEL_PORT "${ENV_FILE}")"
  PANEL_PORT="${PANEL_PORT:-23000}"
  RAG_WORKER_ENABLED="${AGENT_PLATFORM_ENABLE_RAG_WORKER:-$(env_value AGENT_PLATFORM_ENABLE_RAG_WORKER "${ENV_FILE}")}"
  RAG_WORKER_ENABLED="${RAG_WORKER_ENABLED:-0}"
  [[ "${RAG_WORKER_ENABLED}" == "0" || "${RAG_WORKER_ENABLED}" == "1" ]] ||
    die "AGENT_PLATFORM_ENABLE_RAG_WORKER must be 0 or 1"
  CHANNEL_INBOUND_WORKER_ID_VALUE="$(compatible_env_value \
    CHANNEL_INBOUND_WORKER_ID WHATSAPP_INBOX_WORKER_ID channel-inbound-worker-1 "${ENV_FILE}")"
  CHANNEL_INBOUND_POLL_SECONDS_VALUE="$(compatible_env_value \
    CHANNEL_INBOUND_POLL_SECONDS WHATSAPP_INBOX_POLL_SECONDS 1 "${ENV_FILE}")"
  CHANNEL_INBOUND_LEASE_SECONDS_VALUE="$(compatible_env_value \
    CHANNEL_INBOUND_LEASE_SECONDS WHATSAPP_INBOX_STALE_SECONDS 1200 "${ENV_FILE}")"
  # The Compose service and variables remain stable while receipts for older
  # images are valid rollback targets. New images map these aliases to the
  # provider-neutral worker configuration.
  WHATSAPP_INBOX_WORKER_ID_VALUE="${CHANNEL_INBOUND_WORKER_ID_VALUE}"
  WHATSAPP_INBOX_POLL_SECONDS_VALUE="${CHANNEL_INBOUND_POLL_SECONDS_VALUE}"
  WHATSAPP_INBOX_STALE_SECONDS_VALUE="${CHANNEL_INBOUND_LEASE_SECONDS_VALUE}"
  WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE="$(effective_env_value WHATSAPP_INBOX_MAX_ATTEMPTS "${ENV_FILE}")"
  WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE="${WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE:-5}"
  export \
    WHATSAPP_INBOX_WORKER_ID="${WHATSAPP_INBOX_WORKER_ID_VALUE}" \
    WHATSAPP_INBOX_POLL_SECONDS="${WHATSAPP_INBOX_POLL_SECONDS_VALUE}" \
    WHATSAPP_INBOX_STALE_SECONDS="${WHATSAPP_INBOX_STALE_SECONDS_VALUE}" \
    WHATSAPP_INBOX_MAX_ATTEMPTS="${WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE}"
  OUTBOUND_WORKER_ID_VALUE="$(effective_env_value OUTBOUND_WORKER_ID "${ENV_FILE}")"
  OUTBOUND_WORKER_ID_VALUE="${OUTBOUND_WORKER_ID_VALUE:-outbound-worker-1}"
  OUTBOUND_WORKER_POLL_SECONDS_VALUE="$(effective_env_value OUTBOUND_WORKER_POLL_SECONDS "${ENV_FILE}")"
  OUTBOUND_WORKER_POLL_SECONDS_VALUE="${OUTBOUND_WORKER_POLL_SECONDS_VALUE:-1}"
  OUTBOUND_WORKER_MAX_BACKOFF_SECONDS_VALUE="$(effective_env_value OUTBOUND_WORKER_MAX_BACKOFF_SECONDS "${ENV_FILE}")"
  OUTBOUND_WORKER_MAX_BACKOFF_SECONDS_VALUE="${OUTBOUND_WORKER_MAX_BACKOFF_SECONDS_VALUE:-30}"
  OUTBOUND_DISPATCH_STALE_SECONDS_VALUE="$(effective_env_value OUTBOUND_DISPATCH_STALE_SECONDS "${ENV_FILE}")"
  OUTBOUND_DISPATCH_STALE_SECONDS_VALUE="${OUTBOUND_DISPATCH_STALE_SECONDS_VALUE:-300}"
  FOLLOW_UP_WORKER_ID_VALUE="$(effective_env_value FOLLOW_UP_WORKER_ID "${ENV_FILE}")"
  FOLLOW_UP_WORKER_ID_VALUE="${FOLLOW_UP_WORKER_ID_VALUE:-follow-up-worker-1}"
  FOLLOW_UP_WORKER_POLL_SECONDS_VALUE="$(effective_env_value FOLLOW_UP_WORKER_POLL_SECONDS "${ENV_FILE}")"
  FOLLOW_UP_WORKER_POLL_SECONDS_VALUE="${FOLLOW_UP_WORKER_POLL_SECONDS_VALUE:-1}"
  FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS_VALUE="$(effective_env_value FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS "${ENV_FILE}")"
  FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS_VALUE="${FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS_VALUE:-30}"
  FOLLOW_UP_EXECUTION_LEASE_SECONDS_VALUE="$(effective_env_value FOLLOW_UP_EXECUTION_LEASE_SECONDS "${ENV_FILE}")"
  FOLLOW_UP_EXECUTION_LEASE_SECONDS_VALUE="${FOLLOW_UP_EXECUTION_LEASE_SECONDS_VALUE:-120}"
  WEB_EXECUTION_WORKER_ID_VALUE="$(effective_env_value WEB_EXECUTION_WORKER_ID "${ENV_FILE}")"
  WEB_EXECUTION_WORKER_ID_VALUE="${WEB_EXECUTION_WORKER_ID_VALUE:-web-execution-worker-1}"
  WEB_EXECUTION_WORKER_POLL_SECONDS_VALUE="$(effective_env_value WEB_EXECUTION_WORKER_POLL_SECONDS "${ENV_FILE}")"
  WEB_EXECUTION_WORKER_POLL_SECONDS_VALUE="${WEB_EXECUTION_WORKER_POLL_SECONDS_VALUE:-1}"
  WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS_VALUE="$(effective_env_value WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS "${ENV_FILE}")"
  WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS_VALUE="${WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS_VALUE:-30}"
  WEB_EXECUTION_LEASE_SECONDS_VALUE="$(effective_env_value WEB_EXECUTION_LEASE_SECONDS "${ENV_FILE}")"
  WEB_EXECUTION_LEASE_SECONDS_VALUE="${WEB_EXECUTION_LEASE_SECONDS_VALUE:-1200}"

  INTERNAL_TOKEN_FILE="${AGENT_PLATFORM_INTERNAL_TOKEN_SOURCE_FILE:-$(env_value AGENT_PLATFORM_INTERNAL_TOKEN_SOURCE_FILE "${ENV_FILE}")}"
  SOURCE_MASTER_FILE="${AGENT_PLATFORM_SOURCE_MASTER_KEY_FILE:-$(env_value AGENT_PLATFORM_SOURCE_MASTER_KEY_FILE "${ENV_FILE}")}"
  CONTACT_DATA_FILE="${AGENT_PLATFORM_CONTACT_DATA_KEY_FILE:-$(env_value AGENT_PLATFORM_CONTACT_DATA_KEY_FILE "${ENV_FILE}")}"
  CONTACT_LOOKUP_HMAC_FILE="${AGENT_PLATFORM_CONTACT_LOOKUP_HMAC_KEY_FILE:-$(env_value AGENT_PLATFORM_CONTACT_LOOKUP_HMAC_KEY_FILE "${ENV_FILE}")}"
  [[ -n "${INTERNAL_TOKEN_FILE}" && -r "${INTERNAL_TOKEN_FILE}" ]] ||
    die "the internal API token source file is missing or unreadable"
  [[ -n "${SOURCE_MASTER_FILE}" && -r "${SOURCE_MASTER_FILE}" ]] ||
    die "the source master key file is missing or unreadable"
  [[ -n "${CONTACT_DATA_FILE}" && -r "${CONTACT_DATA_FILE}" ]] ||
    die "the contact data key file is missing or unreadable"
  [[ -n "${CONTACT_LOOKUP_HMAC_FILE}" && -r "${CONTACT_LOOKUP_HMAC_FILE}" ]] ||
    die "the contact lookup HMAC key file is missing or unreadable"
  [[ "${INTERNAL_TOKEN_FILE}" =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "the internal API token source path must be an absolute safe path"
  [[ "${SOURCE_MASTER_FILE}" =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "the source master key path must be an absolute safe path"
  [[ "${CONTACT_DATA_FILE}" =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "the contact data key path must be an absolute safe path"
  [[ "${CONTACT_LOOKUP_HMAC_FILE}" =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "the contact lookup HMAC key path must be an absolute safe path"

  COMPOSE_OVERRIDE_FILE="$(mktemp "${TMPDIR:-/tmp}/saltacode-agent-compose.XXXXXX.yml")"
  chmod 0600 "${COMPOSE_OVERRIDE_FILE}"
  cat >"${COMPOSE_OVERRIDE_FILE}" <<EOF
secrets:
  internal_api_token:
    file: ${INTERNAL_TOKEN_FILE}
  source_master_key:
    file: ${SOURCE_MASTER_FILE}
  contact_data_key:
    file: ${CONTACT_DATA_FILE}
  contact_lookup_hmac_key:
    file: ${CONTACT_LOOKUP_HMAC_FILE}
EOF
  trap cleanup_release_files EXIT

  COMPOSE_ARGS=(
    --project-directory "${PLATFORM_ROOT}"
    --env-file "${ENV_FILE}"
    -f "${COMPOSE_FILE}"
    -f "${COMPOSE_OVERRIDE_FILE}"
    --profile rag
  )

  STATE_DIR="${AGENT_PLATFORM_STATE_DIR:-$(env_value AGENT_PLATFORM_STATE_DIR "${ENV_FILE}")}"
  STATE_DIR="${STATE_DIR:-/var/lib/saltacode-agent-platform}"
  RECEIPT_DIR="${STATE_DIR}/receipts"
  ROLLBACK_RECEIPT_DIR="${STATE_DIR}/rollbacks"
  CURRENT_RELEASE_FILE="${STATE_DIR}/current-agent-platform-release"

  ENV_CONTRACT_SHA256="$({
    printf 'AGENT_PLATFORM_DEPLOY_ENV=%s\n' "${DEPLOY_ENV}"
    printf 'AGENT_PLATFORM_ENABLE_RAG_WORKER=%s\n' "${RAG_WORKER_ENABLED}"
    printf 'WHATSAPP_INBOX_WORKER_ID=%s\n' "${WHATSAPP_INBOX_WORKER_ID_VALUE}"
    printf 'WHATSAPP_INBOX_POLL_SECONDS=%s\n' "${WHATSAPP_INBOX_POLL_SECONDS_VALUE}"
    printf 'WHATSAPP_INBOX_STALE_SECONDS=%s\n' "${WHATSAPP_INBOX_STALE_SECONDS_VALUE}"
    printf 'WHATSAPP_INBOX_MAX_ATTEMPTS=%s\n' "${WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE}"
    printf 'OUTBOUND_WORKER_ID=%s\n' "${OUTBOUND_WORKER_ID_VALUE}"
    printf 'OUTBOUND_WORKER_POLL_SECONDS=%s\n' "${OUTBOUND_WORKER_POLL_SECONDS_VALUE}"
    printf 'OUTBOUND_WORKER_MAX_BACKOFF_SECONDS=%s\n' "${OUTBOUND_WORKER_MAX_BACKOFF_SECONDS_VALUE}"
    printf 'OUTBOUND_DISPATCH_STALE_SECONDS=%s\n' "${OUTBOUND_DISPATCH_STALE_SECONDS_VALUE}"
    printf 'FOLLOW_UP_WORKER_ID=%s\n' "${FOLLOW_UP_WORKER_ID_VALUE}"
    printf 'FOLLOW_UP_WORKER_POLL_SECONDS=%s\n' "${FOLLOW_UP_WORKER_POLL_SECONDS_VALUE}"
    printf 'FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS=%s\n' "${FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS_VALUE}"
    printf 'FOLLOW_UP_EXECUTION_LEASE_SECONDS=%s\n' "${FOLLOW_UP_EXECUTION_LEASE_SECONDS_VALUE}"
    printf 'WEB_EXECUTION_WORKER_ID=%s\n' "${WEB_EXECUTION_WORKER_ID_VALUE}"
    printf 'WEB_EXECUTION_WORKER_POLL_SECONDS=%s\n' "${WEB_EXECUTION_WORKER_POLL_SECONDS_VALUE}"
    printf 'WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS=%s\n' "${WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS_VALUE}"
    printf 'WEB_EXECUTION_LEASE_SECONDS=%s\n' "${WEB_EXECUTION_LEASE_SECONDS_VALUE}"
    for key in \
      FASTAPI_ENV LOG_LEVEL POSTGRES_DB POSTGRES_USER REDIS_MAX_MEMORY \
      ADMIN_INITIAL_EMAIL ADMIN_FRONTEND_URL DEFAULT_AGENT_SLUG \
      RETENTION_SWEEP_INTERVAL_SECONDS DOMAIN OPENAI_MODEL OPENAI_WHISPER_MODEL \
      AGENT_API_BIND_ADDRESS AGENT_API_PORT AGENT_PANEL_BIND_ADDRESS AGENT_PANEL_PORT; do
      printf '%s=%s\n' "${key}" "$(effective_env_value "${key}" "${ENV_FILE}")"
    done
  } | sha256sum | awk '{print $1}')"
  COMPOSE_CONTRACT_SHA256="$(compose_contract_sha256 "${COMPOSE_FILE}" "${COMPOSE_OVERRIDE_FILE}")"

  export APP_VERSION="${RELEASE}"
}

compose_release() {
  local release="$1"
  shift
  APP_VERSION="${release}" docker compose "${COMPOSE_ARGS[@]}" "$@"
}

acquire_release_lock() {
  [[ -d "${STATE_DIR}" && -w "${STATE_DIR}" ]] ||
    die "state directory must already exist and be writable: ${STATE_DIR}"
  mkdir -p -- "${RECEIPT_DIR}" "${ROLLBACK_RECEIPT_DIR}"
  chmod 0750 "${STATE_DIR}" "${RECEIPT_DIR}" "${ROLLBACK_RECEIPT_DIR}"
  exec 9>"${STATE_DIR}/deploy.lock"
  flock -n 9 || die "another agent-platform operation holds ${STATE_DIR}/deploy.lock"
}

atomic_write() {
  local destination="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "${destination}.tmp.XXXXXX")"
  printf '%s\n' "${value}" >"${temporary}"
  chmod 0640 "${temporary}"
  mv -f -- "${temporary}" "${destination}"
}

current_release() {
  if [[ -r "${CURRENT_RELEASE_FILE}" ]]; then
    head -n 1 "${CURRENT_RELEASE_FILE}"
  fi
}

deploy_receipt_path() {
  local release="$1"
  valid_release_tag "${release}" || die "invalid receipt release: ${release}"
  printf '%s/%s.receipt' "${RECEIPT_DIR}" "${release}"
}

receipt_value() {
  local receipt="$1"
  local key="$2"
  [[ -r "${receipt}" ]] || die "release receipt is not readable: ${receipt}"
  awk -F= -v wanted="${key}" '$1 == wanted {sub(/^[^=]*=/, ""); print; exit}' "${receipt}"
}

receipt_format_version() {
  local receipt="$1"
  local version
  version="$(receipt_value "${receipt}" format_version)"
  [[ "${version}" == "1" || "${version}" == "2" || "${version}" == "3" ||
     "${version}" == "4" ]] ||
    die "release receipt has an unsupported format version: ${receipt}"
  printf '%s' "${version}"
}

receipt_worker_enabled() {
  local receipt="$1"
  local worker_name="$2"
  local introduced_version="$3"
  local version worker_enabled api_image_id worker_image_id worker_health action
  version="$(receipt_format_version "${receipt}")"
  if (( 10#${version} < 10#${introduced_version} )); then
    printf '0'
    return
  fi

  worker_enabled="$(receipt_value "${receipt}" "${worker_name}_worker_enabled")"
  [[ "${worker_enabled}" == "0" || "${worker_enabled}" == "1" ]] ||
    die "release receipt has an invalid ${worker_name} worker state: ${receipt}"
  if [[ "${worker_enabled}" == "0" ]]; then
    action="$(receipt_value "${receipt}" action)"
    worker_image_id="$(receipt_value "${receipt}" "${worker_name}_worker_image_id")"
    worker_health="$(receipt_value "${receipt}" "${worker_name}_worker_health")"
    [[ 10#${version} -ge 3 && "${action}" == "rollback" ]] ||
      die "release receipt does not require the ${worker_name} worker: ${receipt}"
    [[ "${worker_image_id}" == "none" && "${worker_health}" == "not_applicable" ]] ||
      die "release receipt has invalid disabled ${worker_name} evidence: ${receipt}"
    printf '0'
    return
  fi
  api_image_id="$(receipt_value "${receipt}" api_image_id)"
  worker_image_id="$(receipt_value "${receipt}" "${worker_name}_worker_image_id")"
  [[ -n "${api_image_id}" && "${worker_image_id}" == "${api_image_id}" ]] ||
    die "release receipt does not bind the ${worker_name} worker to the API image: ${receipt}"
  if (( 10#${version} >= 3 )); then
    worker_health="$(receipt_value "${receipt}" "${worker_name}_worker_health")"
    [[ "${worker_health}" == "passed" ]] ||
      die "release receipt does not prove ${worker_name} worker health: ${receipt}"
  fi
  printf '1'
}

receipt_whatsapp_worker_enabled() {
  receipt_worker_enabled "$1" whatsapp 2
}

receipt_channel_inbound_worker_enabled() {
  local receipt="$1"
  local channel_enabled legacy_enabled
  if [[ -z "$(receipt_value "${receipt}" channel_inbound_worker_enabled)" ]]; then
    receipt_whatsapp_worker_enabled "${receipt}"
    return
  fi

  channel_enabled="$(receipt_worker_enabled "${receipt}" channel_inbound 4)"
  legacy_enabled="$(receipt_whatsapp_worker_enabled "${receipt}")"
  [[ "${channel_enabled}" == "${legacy_enabled}" ]] ||
    die "release receipt has inconsistent channel inbound compatibility state: ${receipt}"
  [[ "$(receipt_value "${receipt}" channel_inbound_worker_image_id)" == \
     "$(receipt_value "${receipt}" whatsapp_worker_image_id)" ]] ||
    die "release receipt has inconsistent channel inbound compatibility image: ${receipt}"
  [[ "$(receipt_value "${receipt}" channel_inbound_worker_health)" == \
     "$(receipt_value "${receipt}" whatsapp_worker_health)" ]] ||
    die "release receipt has inconsistent channel inbound compatibility health: ${receipt}"
  printf '%s' "${channel_enabled}"
}

receipt_outbound_worker_enabled() {
  receipt_worker_enabled "$1" outbound 3
}

receipt_web_execution_worker_enabled() {
  receipt_worker_enabled "$1" web_execution 3
}

receipt_follow_up_worker_enabled() {
  receipt_worker_enabled "$1" follow_up 4
}

image_reference() {
  local component="$1"
  local release="$2"
  printf 'localhost/saltacode/agent-platform-%s:%s' "${component}" "${release}"
}

image_id() {
  docker image inspect --format '{{.Id}}' "$1"
}

database_revision() {
  local release="$1"
  local table_exists revision
  table_exists="$(compose_release "${release}" exec -T postgres \
    psql -U "${POSTGRES_USER_VALUE}" -d "${POSTGRES_DB_VALUE}" -Atqc \
    "SELECT to_regclass('public.alembic_version') IS NOT NULL")"
  if [[ "${table_exists}" != "t" ]]; then
    printf 'none'
    return
  fi
  revision="$(compose_release "${release}" exec -T postgres \
    psql -U "${POSTGRES_USER_VALUE}" -d "${POSTGRES_DB_VALUE}" -Atqc \
    "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version")"
  [[ "${revision}" =~ ^[A-Za-z0-9,_-]+$ ]] || die "database revision is invalid"
  printf '%s' "${revision}"
}

probe_host() {
  case "$1" in
    0.0.0.0|::|"[::]") printf '127.0.0.1' ;;
    *) printf '%s' "$1" ;;
  esac
}

verify_release_runtime() {
  local release="$1"
  local channel_inbound_worker_enabled="$2"
  local outbound_worker_enabled="$3"
  local web_execution_worker_enabled="$4"
  local follow_up_worker_enabled="$5"
  local api_host panel_host
  api_host="$(probe_host "${API_BIND_ADDRESS}")"
  panel_host="$(probe_host "${PANEL_BIND_ADDRESS}")"

  compose_release "${release}" exec -T api \
    curl -fsS --max-time 5 http://127.0.0.1:8000/ready >/dev/null
  compose_release "${release}" exec -T panel \
    wget -qO- http://127.0.0.1/ | grep -Fq '<div id="root">'
  curl -fsS --max-time 5 "http://${api_host}:${API_PORT}/ready" >/dev/null
  curl -fsS --max-time 5 "http://${panel_host}:${PANEL_PORT}/" | grep -Fq '<div id="root">'
  # `whatsapp-worker` is the stable Compose identity across the rollback
  # window. Its compatibility module delegates to the provider-neutral worker
  # in current images and remains executable in legacy images.
  verify_worker_runtime "${release}" whatsapp-worker "${channel_inbound_worker_enabled}"
  verify_worker_runtime "${release}" outbound-worker "${outbound_worker_enabled}"
  verify_worker_runtime \
    "${release}" web-execution-worker "${web_execution_worker_enabled}"
  verify_worker_runtime "${release}" follow-up-worker "${follow_up_worker_enabled}"
}

verify_worker_runtime() {
  local release="$1"
  local service="$2"
  local enabled="$3"
  local running_services container_id expected_reference configured_reference
  local expected_image_id health_status running_image_id
  [[ "${enabled}" == "0" || "${enabled}" == "1" ]] ||
    die "${service} receipt state must be 0 or 1"

  running_services="$(compose_release "${release}" ps --status running --services)"
  if [[ "${enabled}" == "0" ]]; then
    ! grep -Fxq "${service}" <<<"${running_services}" ||
      die "${service} is running for a release whose receipt predates it"
    return
  fi

  grep -Fxq "${service}" <<<"${running_services}" ||
    die "${service} is not running"
  container_id="$(compose_release "${release}" ps -q "${service}")"
  [[ "${container_id}" =~ ^[a-f0-9]{64}$ ]] ||
    die "${service} container identity is invalid"

  expected_reference="$(image_reference api "${release}")"
  configured_reference="$(docker container inspect --format '{{.Config.Image}}' "${container_id}")"
  [[ "${configured_reference}" == "${expected_reference}" ]] ||
    die "${service} does not use the immutable API image reference"
  expected_image_id="$(image_id "${expected_reference}")"
  running_image_id="$(docker container inspect --format '{{.Image}}' "${container_id}")"
  [[ "${running_image_id}" == "${expected_image_id}" ]] ||
    die "${service} image ID does not match the immutable API image"
  health_status="$(docker container inspect --format '{{.State.Health.Status}}' "${container_id}")"
  [[ "${health_status}" == "healthy" ]] || die "${service} is not healthy"
}

stop_application_services() {
  local release="$1"
  compose_release "${release}" stop --timeout 30 \
    panel rag-worker follow-up-worker web-execution-worker outbound-worker whatsapp-worker api >/dev/null
}

start_application_services() {
  local release="$1"
  local rag_enabled="$2"
  local channel_inbound_worker_enabled="$3"
  local outbound_worker_enabled="$4"
  local web_execution_worker_enabled="$5"
  local follow_up_worker_enabled="$6"
  [[ "${rag_enabled}" == "0" || "${rag_enabled}" == "1" ]] ||
    die "RAG worker receipt state must be 0 or 1"
  [[ "${channel_inbound_worker_enabled}" == "0" || "${channel_inbound_worker_enabled}" == "1" ]] ||
    die "channel inbound worker receipt state must be 0 or 1"
  [[ "${outbound_worker_enabled}" == "0" || "${outbound_worker_enabled}" == "1" ]] ||
    die "outbound worker receipt state must be 0 or 1"
  [[ "${web_execution_worker_enabled}" == "0" || "${web_execution_worker_enabled}" == "1" ]] ||
    die "web execution worker receipt state must be 0 or 1"
  [[ "${follow_up_worker_enabled}" == "0" || "${follow_up_worker_enabled}" == "1" ]] ||
    die "follow-up worker receipt state must be 0 or 1"
  compose_release "${release}" up -d --wait --no-deps api
  compose_release "${release}" up -d --wait --no-deps panel
  if [[ "${rag_enabled}" == "1" ]]; then
    compose_release "${release}" up -d --no-deps rag-worker
  fi
  if [[ "${channel_inbound_worker_enabled}" == "1" ]]; then
    compose_release "${release}" up -d --wait --no-deps whatsapp-worker
  fi
  if [[ "${outbound_worker_enabled}" == "1" ]]; then
    compose_release "${release}" up -d --wait --no-deps outbound-worker
  fi
  if [[ "${web_execution_worker_enabled}" == "1" ]]; then
    compose_release "${release}" up -d --wait --no-deps web-execution-worker
  fi
  if [[ "${follow_up_worker_enabled}" == "1" ]]; then
    compose_release "${release}" up -d --wait --no-deps follow-up-worker
  fi
}

assert_release_restorable() {
  local release="$1"
  local current_db_revision="$2"
  local receipt expected
  receipt="$(deploy_receipt_path "${release}")"
  [[ -r "${receipt}" ]] || die "no release receipt exists for ${release}"
  [[ "$(receipt_value "${receipt}" component)" == "agent-platform" ]] ||
    die "receipt ${receipt} is not an agent-platform receipt"
  [[ "$(receipt_value "${receipt}" action)" == "deploy" ]] ||
    die "receipt ${receipt} is not a deploy receipt"
  [[ "$(receipt_value "${receipt}" database_revision_after)" == "${current_db_revision}" ]] ||
    die "release ${release} is not compatible with database revision ${current_db_revision}"
  [[ "$(receipt_value "${receipt}" compose_contract_sha256)" == "${COMPOSE_CONTRACT_SHA256}" ]] ||
    die "release ${release} uses a different Compose contract"
  [[ "$(receipt_value "${receipt}" environment_contract_sha256)" == "${ENV_CONTRACT_SHA256}" ]] ||
    die "release ${release} uses a different environment contract"
  receipt_format_version "${receipt}" >/dev/null
  receipt_channel_inbound_worker_enabled "${receipt}" >/dev/null
  receipt_outbound_worker_enabled "${receipt}" >/dev/null
  receipt_web_execution_worker_enabled "${receipt}" >/dev/null
  receipt_follow_up_worker_enabled "${receipt}" >/dev/null

  expected="$(receipt_value "${receipt}" api_image_id)"
  [[ "$(image_id "$(image_reference api "${release}")")" == "${expected}" ]] ||
    die "API image tag for ${release} no longer matches its immutable receipt"
  expected="$(receipt_value "${receipt}" panel_image_id)"
  [[ "$(image_id "$(image_reference panel "${release}")")" == "${expected}" ]] ||
    die "panel image tag for ${release} no longer matches its immutable receipt"
}

record_deploy_receipt() {
  local previous_release="$1"
  local database_before="$2"
  local database_after="$3"
  local api_image_id="$4"
  local panel_image_id="$5"
  local timestamp receipt temporary commit
  timestamp="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  receipt="$(deploy_receipt_path "${RELEASE}")"
  commit="$(git -C "${PLATFORM_ROOT}" rev-parse HEAD)"
  [[ ! -e "${receipt}" ]] || die "release receipt already exists: ${receipt}"
  temporary="$(mktemp "${receipt}.tmp.XXXXXX")"

  umask 0027
  {
    printf 'format_version=4\n'
    printf 'component=agent-platform\n'
    printf 'action=deploy\n'
    printf 'release=%s\n' "${RELEASE}"
    printf 'previous_release=%s\n' "${previous_release:-none}"
    printf 'deployed_at=%s\n' "${timestamp}"
    printf 'environment=%s\n' "${DEPLOY_ENV}"
    printf 'git_commit=%s\n' "${commit}"
    printf 'compose_contract_sha256=%s\n' "${COMPOSE_CONTRACT_SHA256}"
    printf 'environment_contract_sha256=%s\n' "${ENV_CONTRACT_SHA256}"
    printf 'database_revision_before=%s\n' "${database_before}"
    printf 'database_revision_after=%s\n' "${database_after}"
    printf 'api_image_id=%s\n' "${api_image_id}"
    printf 'panel_image_id=%s\n' "${panel_image_id}"
    printf 'rag_worker_enabled=%s\n' "${RAG_WORKER_ENABLED}"
    printf 'channel_inbound_worker_enabled=1\n'
    printf 'channel_inbound_worker_image_id=%s\n' "${api_image_id}"
    printf 'channel_inbound_worker_health=passed\n'
    printf 'whatsapp_worker_enabled=1\n'
    printf 'whatsapp_worker_image_id=%s\n' "${api_image_id}"
    printf 'whatsapp_worker_health=passed\n'
    printf 'outbound_worker_enabled=1\n'
    printf 'outbound_worker_image_id=%s\n' "${api_image_id}"
    printf 'outbound_worker_health=passed\n'
    printf 'web_execution_worker_enabled=1\n'
    printf 'web_execution_worker_image_id=%s\n' "${api_image_id}"
    printf 'web_execution_worker_health=passed\n'
    printf 'follow_up_worker_enabled=1\n'
    printf 'follow_up_worker_image_id=%s\n' "${api_image_id}"
    printf 'follow_up_worker_health=passed\n'
    printf 'verification=passed\n'
  } >"${temporary}"
  chmod 0640 "${temporary}"
  mv -- "${temporary}" "${receipt}"
  atomic_write "${CURRENT_RELEASE_FILE}" "${RELEASE}"
}

record_rollback_receipt() {
  local from_release="$1"
  local target_release="$2"
  local database_revision="$3"
  local timestamp receipt temporary target_receipt target_rag target_channel_inbound
  local target_outbound target_web_execution target_follow_up
  local target_api_image_id target_panel_image_id
  timestamp="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  receipt="${ROLLBACK_RECEIPT_DIR}/${timestamp}-${from_release}-to-${target_release}.receipt"
  [[ ! -e "${receipt}" ]] || die "rollback receipt already exists: ${receipt}"
  target_receipt="$(deploy_receipt_path "${target_release}")"
  target_rag="$(receipt_value "${target_receipt}" rag_worker_enabled)"
  [[ "${target_rag}" == "0" || "${target_rag}" == "1" ]] ||
    die "target release receipt has an invalid RAG worker state"
  target_channel_inbound="$(receipt_channel_inbound_worker_enabled "${target_receipt}")"
  target_outbound="$(receipt_outbound_worker_enabled "${target_receipt}")"
  target_web_execution="$(receipt_web_execution_worker_enabled "${target_receipt}")"
  target_follow_up="$(receipt_follow_up_worker_enabled "${target_receipt}")"
  target_api_image_id="$(receipt_value "${target_receipt}" api_image_id)"
  target_panel_image_id="$(receipt_value "${target_receipt}" panel_image_id)"
  temporary="$(mktemp "${receipt}.tmp.XXXXXX")"
  umask 0027
  {
    printf 'format_version=4\n'
    printf 'component=agent-platform\n'
    printf 'action=rollback\n'
    printf 'from_release=%s\n' "${from_release}"
    printf 'release=%s\n' "${target_release}"
    printf 'rolled_back_at=%s\n' "${timestamp}"
    printf 'database_revision=%s\n' "${database_revision}"
    printf 'database_restored=false\n'
    printf 'volumes_removed=false\n'
    printf 'api_image_id=%s\n' "${target_api_image_id}"
    printf 'panel_image_id=%s\n' "${target_panel_image_id}"
    printf 'rag_worker_enabled=%s\n' "${target_rag}"
    printf 'channel_inbound_worker_enabled=%s\n' "${target_channel_inbound}"
    printf 'channel_inbound_worker_image_id=%s\n' "$([[ "${target_channel_inbound}" == "1" ]] && printf '%s' "${target_api_image_id}" || printf none)"
    printf 'channel_inbound_worker_health=%s\n' "$([[ "${target_channel_inbound}" == "1" ]] && printf passed || printf not_applicable)"
    printf 'whatsapp_worker_enabled=%s\n' "${target_channel_inbound}"
    printf 'whatsapp_worker_image_id=%s\n' "$([[ "${target_channel_inbound}" == "1" ]] && printf '%s' "${target_api_image_id}" || printf none)"
    printf 'whatsapp_worker_health=%s\n' "$([[ "${target_channel_inbound}" == "1" ]] && printf passed || printf not_applicable)"
    printf 'outbound_worker_enabled=%s\n' "${target_outbound}"
    printf 'outbound_worker_image_id=%s\n' "$([[ "${target_outbound}" == "1" ]] && printf '%s' "${target_api_image_id}" || printf none)"
    printf 'outbound_worker_health=%s\n' "$([[ "${target_outbound}" == "1" ]] && printf passed || printf not_applicable)"
    printf 'web_execution_worker_enabled=%s\n' "${target_web_execution}"
    printf 'web_execution_worker_image_id=%s\n' "$([[ "${target_web_execution}" == "1" ]] && printf '%s' "${target_api_image_id}" || printf none)"
    printf 'web_execution_worker_health=%s\n' "$([[ "${target_web_execution}" == "1" ]] && printf passed || printf not_applicable)"
    printf 'follow_up_worker_enabled=%s\n' "${target_follow_up}"
    printf 'follow_up_worker_image_id=%s\n' "$([[ "${target_follow_up}" == "1" ]] && printf '%s' "${target_api_image_id}" || printf none)"
    printf 'follow_up_worker_health=%s\n' "$([[ "${target_follow_up}" == "1" ]] && printf passed || printf not_applicable)"
    printf 'verification=passed\n'
  } >"${temporary}"
  chmod 0640 "${temporary}"
  mv -- "${temporary}" "${receipt}"
  atomic_write "${CURRENT_RELEASE_FILE}" "${target_release}"
}
