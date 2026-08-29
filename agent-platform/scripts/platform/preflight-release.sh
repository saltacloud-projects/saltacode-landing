#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release-lib.sh
source "${SCRIPT_DIR}/release-lib.sh"

configure_release_environment "${1:-}"

for command in awk cat chmod curl date docker flock git grep head mkdir mktemp mv rm sha256sum stat; do
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
[[ -f "${PLATFORM_ROOT}/fastapi/Dockerfile" ]] || die "FastAPI Dockerfile is missing"
[[ -f "${PLATFORM_ROOT}/frontend/Dockerfile" ]] || die "panel Dockerfile is missing"
[[ "${POSTGRES_DB_VALUE}" =~ ^[A-Za-z0-9_-]+$ ]] || die "POSTGRES_DB is invalid"
[[ "${POSTGRES_USER_VALUE}" =~ ^[A-Za-z0-9_-]+$ ]] || die "POSTGRES_USER is invalid"
[[ "${API_PORT}" =~ ^[0-9]+$ && "${PANEL_PORT}" =~ ^[0-9]+$ ]] ||
  die "agent API and panel ports must be numeric"
(( API_PORT >= 1024 && API_PORT <= 65535 )) || die "AGENT_API_PORT is invalid"
(( PANEL_PORT >= 1024 && PANEL_PORT <= 65535 )) || die "AGENT_PANEL_PORT is invalid"

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

printf 'agent-platform preflight passed: environment=%s release=%s rag_worker=%s\n' \
  "${DEPLOY_ENV}" "${RELEASE}" "${RAG_WORKER_ENABLED}"
