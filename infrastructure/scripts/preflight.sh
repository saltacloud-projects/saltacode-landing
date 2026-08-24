#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

configure_environment "${1:-}"
component="${2:-all}"
[[ "${component}" == "site" || "${component}" == "agent" || "${component}" == "all" ]] ||
  die "preflight component must be site, agent, or all"

for command in awk cat curl docker flock stat; do
  require_command "${command}"
done

docker compose version >/dev/null
docker info >/dev/null
docker compose up --help | grep -q -- '--wait' || die "Docker Compose must support up --wait"

required_paths=()
if [[ "${component}" == "site" || "${component}" == "all" ]]; then
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
fi
if [[ "${component}" == "agent" || "${component}" == "all" ]]; then
  required_paths+=("${PROJECT_ROOT}/agent-ai/Dockerfile")
fi
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
token_gid="${SALTACODE_AGENT_INTERNAL_TOKEN_GID:-$(env_value SALTACODE_AGENT_INTERNAL_TOKEN_GID "${ENV_FILE}")}"
[[ "${token_gid}" =~ ^[1-9][0-9]*$ ]] ||
  die "SALTACODE_AGENT_INTERNAL_TOKEN_GID must be a positive numeric group ID"
actual_token_gid="$(stat -c '%g' "${token_file}")"
[[ "${actual_token_gid}" == "${token_gid}" ]] ||
  die "the external agent token file group ${actual_token_gid} does not match configured group ${token_gid}"

app_env="${SALTACODE_APP_ENV:-$(env_value SALTACODE_APP_ENV "${ENV_FILE}")}"
limiter="${SALTACODE_RATE_LIMIT_BACKEND:-$(env_value SALTACODE_RATE_LIMIT_BACKEND "${ENV_FILE}")}"
if [[ ( "${component}" == "site" || "${component}" == "all" ) &&
      "${app_env}" == "production" && "${limiter}" != "redis" ]]; then
  die "production BFF requires the Redis rate-limit backend"
fi

compose config --quiet
printf 'preflight passed: environment=%s release=%s\n' "${DEPLOY_ENV}" "${RELEASE}"
