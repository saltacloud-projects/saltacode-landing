#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

configure_environment "${1:-}"
component="${2:-all}"
[[ "${component}" == "site" || "${component}" == "all" ]] ||
  die "preflight component must be site or all"

for command in awk cat curl docker flock stat; do
  require_command "${command}"
done

docker compose version >/dev/null
docker info >/dev/null
docker compose up --help | grep -q -- '--wait' || die "Docker Compose must support up --wait"

required_paths=()
required_paths+=("${PROJECT_ROOT}/frontend/Dockerfile" "${PROJECT_ROOT}/backend/Dockerfile")
[[ "${REDIS_IMAGE}" =~ ^((docker\.io/)?library/)?redis:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$ ]] ||
  die "SALTACODE_REDIS_IMAGE must be an official Redis tag pinned to a real sha256 digest"
redis_url="${SALTACODE_REDIS_URL:-$(env_value SALTACODE_REDIS_URL "${ENV_FILE}")}"
[[ "${redis_url}" == "redis://redis:6379/0" ]] ||
  die "SALTACODE_REDIS_URL must target the private redis service"
redis_uid="${SALTACODE_REDIS_UID:-$(env_value SALTACODE_REDIS_UID "${ENV_FILE}")}"
redis_gid="${SALTACODE_REDIS_GID:-$(env_value SALTACODE_REDIS_GID "${ENV_FILE}")}"
[[ "${redis_uid}" =~ ^[1-9][0-9]*$ && "${redis_gid}" =~ ^[1-9][0-9]*$ ]] ||
  die "Redis UID and GID must be positive numeric image-contract values"
for path in "${required_paths[@]}"; do
  [[ -f "${path}" ]] || die "required build input is missing: ${path}"
done

token_file="${SALTACODE_AGENT_INTERNAL_TOKEN_SOURCE_FILE:-$(env_value SALTACODE_AGENT_INTERNAL_TOKEN_SOURCE_FILE "${ENV_FILE}")}"
[[ -n "${token_file}" && -f "${token_file}" && -r "${token_file}" ]] ||
  die "the external agent token file is missing or unreadable"
token_content="$(cat -- "${token_file}")"
token_content="${token_content%$'\r'}"
[[ "${token_content}" != *$'\n'* && "${token_content}" != *$'\r'* ]] ||
  die "the external agent token file must contain exactly one token"
(( ${#token_content} >= 32 && ${#token_content} <= 4096 )) ||
  die "the external agent token must contain between 32 and 4096 characters"
unset token_content
token_mode="$(stat -c '%a' "${token_file}")"
[[ "${token_mode}" == "440" || "${token_mode}" == "640" ]] ||
  die "the external agent token file mode must be 0440 or 0640"
token_gid="${SALTACODE_SECRET_GID:-$(env_value SALTACODE_SECRET_GID "${ENV_FILE}")}"
[[ "${token_gid}" =~ ^[1-9][0-9]*$ ]] ||
  die "SALTACODE_SECRET_GID must be a positive numeric group ID"
actual_token_gid="$(stat -c '%g' "${token_file}")"
[[ "${actual_token_gid}" == "${token_gid}" ]] ||
  die "the external agent token file group ${actual_token_gid} does not match configured group ${token_gid}"

session_file="${SALTACODE_SESSION_SIGNING_SECRET_SOURCE_FILE:-$(env_value SALTACODE_SESSION_SIGNING_SECRET_SOURCE_FILE "${ENV_FILE}")}"
[[ -n "${session_file}" && -f "${session_file}" && -r "${session_file}" ]] ||
  die "the session signing secret file is missing or unreadable"
session_content="$(cat -- "${session_file}")"
session_content="${session_content%$'\r'}"
[[ "${session_content}" != *$'\n'* && "${session_content}" != *$'\r'* ]] ||
  die "the session signing secret file must contain exactly one secret"
(( ${#session_content} >= 32 && ${#session_content} <= 4096 )) ||
  die "the session signing secret must contain between 32 and 4096 characters"
unset session_content
session_mode="$(stat -c '%a' "${session_file}")"
[[ "${session_mode}" == "440" || "${session_mode}" == "640" ]] ||
  die "the session signing secret file mode must be 0440 or 0640"
actual_session_gid="$(stat -c '%g' "${session_file}")"
[[ "${actual_session_gid}" == "${token_gid}" ]] ||
  die "the session secret file group ${actual_session_gid} does not match configured group ${token_gid}"

app_env="${SALTACODE_APP_ENV:-$(env_value SALTACODE_APP_ENV "${ENV_FILE}")}"
limiter="${SALTACODE_RATE_LIMIT_BACKEND:-$(env_value SALTACODE_RATE_LIMIT_BACKEND "${ENV_FILE}")}"
if [[ ( "${component}" == "site" || "${component}" == "all" ) &&
      "${app_env}" == "production" && "${limiter}" != "redis" ]]; then
  die "production BFF requires the Redis rate-limit backend"
fi

compose config --quiet
printf 'preflight passed: environment=%s release=%s\n' "${DEPLOY_ENV}" "${RELEASE}"
