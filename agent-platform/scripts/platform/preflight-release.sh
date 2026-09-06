#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release-lib.sh
source "${SCRIPT_DIR}/release-lib.sh"

configure_release_environment "${1:-}"

for command in awk cat chmod cmp curl date docker flock git grep head mkdir mktemp mv rm sha256sum stat; do
  require_command "${command}"
done
docker compose version >/dev/null
docker info >/dev/null
docker compose up --help | grep -q -- '--wait' ||
  die "Docker Compose must support up --wait"

[[ -f "${ENV_FILE}" && ! -L "${ENV_FILE}" ]] ||
  die "the environment file must be a regular file, not a symlink"
[[ "${STATE_DIR}" =~ ^/[A-Za-z0-9._/-]+$ ]] ||
  die "AGENT_PLATFORM_STATE_DIR must be an absolute safe path"
[[ -d "${STATE_DIR}" && ! -L "${STATE_DIR}" && -w "${STATE_DIR}" ]] ||
  die "the state directory must exist, be writable, and not be a symlink"
[[ -f "${PLATFORM_ROOT}/api/Dockerfile" ]] || die "Agent API Dockerfile is missing"
[[ -f "${PLATFORM_ROOT}/panel/Dockerfile" ]] || die "panel Dockerfile is missing"
[[ "${POSTGRES_DB_VALUE}" =~ ^[A-Za-z0-9_-]+$ ]] || die "POSTGRES_DB is invalid"
[[ "${POSTGRES_USER_VALUE}" =~ ^[A-Za-z0-9_-]+$ ]] || die "POSTGRES_USER is invalid"
[[ "${API_PORT}" =~ ^[0-9]+$ && "${PANEL_PORT}" =~ ^[0-9]+$ ]] ||
  die "agent API and panel ports must be numeric"
(( API_PORT >= 1024 && API_PORT <= 65535 )) || die "AGENT_API_PORT is invalid"
(( PANEL_PORT >= 1024 && PANEL_PORT <= 65535 )) || die "AGENT_PANEL_PORT is invalid"
(( ${#CHANNEL_INBOUND_WORKER_ID_VALUE} >= 1 && ${#CHANNEL_INBOUND_WORKER_ID_VALUE} <= 70 )) ||
  die "CHANNEL_INBOUND_WORKER_ID length is invalid"
awk -v value="${CHANNEL_INBOUND_POLL_SECONDS_VALUE}" 'BEGIN {
  valid = value ~ /^([0-9]+([.][0-9]+)?|[.][0-9]+)$/ && value > 0 && value <= 60
  exit !valid
}' || die "CHANNEL_INBOUND_POLL_SECONDS must be greater than 0 and at most 60"
if [[ ! "${CHANNEL_INBOUND_LEASE_SECONDS_VALUE}" =~ ^[0-9]+$ ]] ||
   (( 10#${CHANNEL_INBOUND_LEASE_SECONDS_VALUE} < 960 || 10#${CHANNEL_INBOUND_LEASE_SECONDS_VALUE} > 86400 )); then
  die "CHANNEL_INBOUND_LEASE_SECONDS must be between 960 and 86400"
fi
if [[ ! "${WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE}" =~ ^[0-9]+$ ]] ||
   (( 10#${WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE} < 1 || 10#${WHATSAPP_INBOX_MAX_ATTEMPTS_VALUE} > 20 )); then
  die "WHATSAPP_INBOX_MAX_ATTEMPTS must be between 1 and 20"
fi
for worker_id in \
  "${OUTBOUND_WORKER_ID_VALUE}" \
  "${WEB_EXECUTION_WORKER_ID_VALUE}" \
  "${FOLLOW_UP_WORKER_ID_VALUE}"; do
  (( ${#worker_id} >= 1 && ${#worker_id} <= 70 )) ||
    die "worker identifier length must be between 1 and 70"
done
validate_decimal_range() {
  local value="$1"
  local minimum="$2"
  local maximum="$3"
  local label="$4"
  awk -v value="${value}" -v minimum="${minimum}" -v maximum="${maximum}" 'BEGIN {
    valid = value ~ /^([0-9]+([.][0-9]+)?|[.][0-9]+)$/ &&
      value >= minimum && value <= maximum
    exit !valid
  }' || die "${label} must be between ${minimum} and ${maximum}"
}
validate_decimal_range "${OUTBOUND_WORKER_POLL_SECONDS_VALUE}" 0.000001 60 \
  OUTBOUND_WORKER_POLL_SECONDS
validate_decimal_range "${OUTBOUND_WORKER_MAX_BACKOFF_SECONDS_VALUE}" 1 300 \
  OUTBOUND_WORKER_MAX_BACKOFF_SECONDS
validate_decimal_range "${WEB_EXECUTION_WORKER_POLL_SECONDS_VALUE}" 0.000001 60 \
  WEB_EXECUTION_WORKER_POLL_SECONDS
validate_decimal_range "${WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS_VALUE}" 1 300 \
  WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS
validate_decimal_range "${FOLLOW_UP_WORKER_POLL_SECONDS_VALUE}" 0.000001 60 \
  FOLLOW_UP_WORKER_POLL_SECONDS
validate_decimal_range "${FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS_VALUE}" 1 300 \
  FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS
awk -v poll="${WEB_EXECUTION_WORKER_POLL_SECONDS_VALUE}" \
    -v backoff="${WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS_VALUE}" \
    'BEGIN { exit !(backoff >= poll) }' ||
  die "WEB_EXECUTION_WORKER_MAX_BACKOFF_SECONDS must not be below its poll interval"
awk -v poll="${FOLLOW_UP_WORKER_POLL_SECONDS_VALUE}" \
    -v backoff="${FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS_VALUE}" \
    'BEGIN { exit !(backoff >= poll) }' ||
  die "FOLLOW_UP_WORKER_MAX_BACKOFF_SECONDS must not be below its poll interval"
if [[ ! "${OUTBOUND_DISPATCH_STALE_SECONDS_VALUE}" =~ ^[0-9]+$ ]] ||
   (( 10#${OUTBOUND_DISPATCH_STALE_SECONDS_VALUE} < 60 || 10#${OUTBOUND_DISPATCH_STALE_SECONDS_VALUE} > 86400 )); then
  die "OUTBOUND_DISPATCH_STALE_SECONDS must be between 60 and 86400"
fi
if [[ ! "${WEB_EXECUTION_LEASE_SECONDS_VALUE}" =~ ^[0-9]+$ ]] ||
   (( 10#${WEB_EXECUTION_LEASE_SECONDS_VALUE} <= 900 || 10#${WEB_EXECUTION_LEASE_SECONDS_VALUE} > 86400 )); then
  die "WEB_EXECUTION_LEASE_SECONDS must be greater than 900 and at most 86400"
fi
if [[ ! "${FOLLOW_UP_EXECUTION_LEASE_SECONDS_VALUE}" =~ ^[0-9]+$ ]] ||
   (( 10#${FOLLOW_UP_EXECUTION_LEASE_SECONDS_VALUE} < 30 || 10#${FOLLOW_UP_EXECUTION_LEASE_SECONDS_VALUE} > 3600 )); then
  die "FOLLOW_UP_EXECUTION_LEASE_SECONDS must be between 30 and 3600"
fi

env_mode="$(stat -c '%a' "${ENV_FILE}")"
[[ "${env_mode}" == "600" || "${env_mode}" == "640" ]] ||
  die "the environment file mode must be 0600 or 0640"

validate_secret_file() {
  local path="$1"
  local label="$2"
  local minimum="$3"
  local maximum="$4"
  local mode value
  [[ -f "${path}" && ! -L "${path}" ]] ||
    die "${label} must be a regular file, not a symlink"
  mode="$(stat -c '%a' "${path}")"
  [[ "${mode}" == "400" || "${mode}" == "440" || "${mode}" == "600" || "${mode}" == "640" ]] ||
    die "${label} file mode must be 0400, 0440, 0600, or 0640"
  [[ "$(awk 'END {print NR}' "${path}")" == "1" ]] ||
    die "${label} file must contain exactly one line"
  value="$(cat -- "${path}")"
  value="${value%$'\r'}"
  [[ "${value}" != *$'\n'* && "${value}" != *$'\r'* ]] ||
    die "${label} file must contain exactly one line"
  (( ${#value} >= minimum && ${#value} <= maximum )) ||
    die "${label} length is outside its accepted range"
  unset value
}

validate_secret_file "${INTERNAL_TOKEN_FILE}" "internal API token" 32 4096
validate_secret_file "${SOURCE_MASTER_FILE}" "source master key" 32 4096
validate_secret_file "${CONTACT_DATA_FILE}" "contact data key" 44 44
validate_secret_file "${CONTACT_LOOKUP_HMAC_FILE}" "contact lookup HMAC key" 32 4096
grep -Eq '^[A-Za-z0-9_-]{43}=$' "${CONTACT_DATA_FILE}" ||
  die "contact data key must be a Fernet-compatible key"
! cmp -s "${CONTACT_DATA_FILE}" "${CONTACT_LOOKUP_HMAC_FILE}" ||
  die "contact encryption and lookup keys must be distinct"

reject_placeholder() {
  local key="$1"
  local minimum="$2"
  local value lower
  value="$(effective_env_value "${key}" "${ENV_FILE}")"
  lower="${value,,}"
  (( ${#value} >= minimum )) || die "${key} is missing or too short"
  [[ "${lower}" != *generate* && "${lower}" != *change-me* && "${lower}" != *replace* ]] ||
    die "${key} still contains a placeholder"
}

reject_placeholder POSTGRES_PASSWORD 16
reject_placeholder JWT_SECRET_KEY 32
reject_placeholder ADMIN_INITIAL_PASSWORD 12

if [[ "${DEPLOY_ENV}" == "production" ]]; then
  production_domain="$(effective_env_value DOMAIN "${ENV_FILE}")"
  admin_origin="$(effective_env_value ADMIN_FRONTEND_URL "${ENV_FILE}")"
  [[ "$(effective_env_value FASTAPI_ENV "${ENV_FILE}")" == "production" ]] ||
    die "production release requires FASTAPI_ENV=production"
  [[ "${API_BIND_ADDRESS}" == "127.0.0.1" && "${PANEL_BIND_ADDRESS}" == "127.0.0.1" ]] ||
    die "production agent API and panel must bind to 127.0.0.1"
  [[ "${production_domain}" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ &&
     "${production_domain,,}" != "localhost" &&
     "${production_domain,,}" != *replace* &&
     "${production_domain,,}" != *.invalid &&
     "${production_domain,,}" != *.test ]] ||
    die "production DOMAIN must be a real hostname without placeholders"
  [[ "${admin_origin}" =~ ^https://[A-Za-z0-9][A-Za-z0-9.-]+(:[0-9]+)?$ &&
     "${admin_origin,,}" != *replace* &&
     "${admin_origin,,}" != *.invalid* &&
     "${admin_origin,,}" != *.test* ]] ||
    die "production ADMIN_FRONTEND_URL must be a real HTTPS origin without a path"
  [[ -z "$(git -C "${PLATFORM_ROOT}" status --porcelain)" ]] ||
    die "production release requires a clean Git checkout"
fi

compose_release "${RELEASE}" config --quiet
images="$(compose_release "${RELEASE}" config --images)"
grep -Fxq "$(image_reference api "${RELEASE}")" <<<"${images}" ||
  die "effective API image does not use the immutable release tag"
grep -Fxq "$(image_reference panel "${RELEASE}")" <<<"${images}" ||
  die "effective panel image does not use the immutable release tag"

rendered_service_value() {
  local service="$1"
  local key="$2"
  compose_release "${RELEASE}" config "${service}" | awk \
    -v service="${service}" -v wanted="${key}" '
    $0 == "  " service ":" {inside = 1; next}
    inside && /^  [A-Za-z0-9_-]+:$/ {exit}
    inside {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      if (index(line, wanted ":") == 1) {
        sub(/^[^:]+:[[:space:]]*/, "", line)
        if (substr(line, 1, 1) == "\"" && substr(line, length(line), 1) == "\"") {
          line = substr(line, 2, length(line) - 2)
        }
        print line
        exit
      }
    }
  '
}

for worker_service in \
  whatsapp-worker outbound-worker web-execution-worker follow-up-worker; do
  worker_image="$(rendered_service_value "${worker_service}" image)"
  [[ "${worker_image}" == "$(image_reference api "${RELEASE}")" ]] ||
    die "effective ${worker_service} must use the immutable API image"
done
# `whatsapp-worker` and its environment keys remain the deployment aliases
# until legacy images leave the rollback window. Their rendered values must
# equal the provider-neutral values resolved by release-lib.
for worker_contract in \
  "whatsapp-worker:WHATSAPP_INBOX:WORKER_ID POLL_SECONDS STALE_SECONDS MAX_ATTEMPTS" \
  "outbound-worker:OUTBOUND:WORKER_ID WORKER_POLL_SECONDS WORKER_MAX_BACKOFF_SECONDS DISPATCH_STALE_SECONDS" \
  "web-execution-worker:WEB_EXECUTION:WORKER_ID WORKER_POLL_SECONDS WORKER_MAX_BACKOFF_SECONDS LEASE_SECONDS" \
  "follow-up-worker:FOLLOW_UP:WORKER_ID WORKER_POLL_SECONDS WORKER_MAX_BACKOFF_SECONDS EXECUTION_LEASE_SECONDS"; do
  service="${worker_contract%%:*}"
  remainder="${worker_contract#*:}"
  prefix="${remainder%%:*}"
  settings="${remainder#*:}"
  for worker_setting in ${settings}; do
    variable="${prefix}_${worker_setting}"
    script_value_name="${variable}_VALUE"
    rendered_value="$(rendered_service_value "${service}" "${variable}")"
    [[ "${rendered_value}" == "${!script_value_name}" ]] ||
      die "effective ${variable} differs from the release contract"
  done
done

printf 'agent-platform preflight passed: environment=%s release=%s rag_worker=%s durable_workers=required\n' \
  "${DEPLOY_ENV}" "${RELEASE}" "${RAG_WORKER_ENABLED}"
