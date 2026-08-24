#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

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
  local value

  value="$({
    awk -v wanted="${key}" '
      /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
      {
        line = $0
        sub(/^[[:space:]]*export[[:space:]]+/, "", line)
        split(line, parts, "=")
        name = parts[1]
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
  } || true)"

  printf '%s' "${value}"
}

configure_environment() {
  ENV_FILE="${SALTACODE_ENV_FILE:-${1:-}}"
  [[ -n "${ENV_FILE}" ]] || die "set SALTACODE_ENV_FILE or pass an environment file"
  [[ -r "${ENV_FILE}" ]] || die "environment file is not readable: ${ENV_FILE}"

  DEPLOY_ENV="${SALTACODE_DEPLOY_ENV:-production}"
  [[ "${DEPLOY_ENV}" == "production" || "${DEPLOY_ENV}" == "sandbox" ]] ||
    die "SALTACODE_DEPLOY_ENV must be production or sandbox"

  RELEASE="${SALTACODE_RELEASE:-$(env_value SALTACODE_RELEASE "${ENV_FILE}")}"
  [[ "${RELEASE}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] ||
    die "SALTACODE_RELEASE must be a non-placeholder immutable tag"
  [[ "${RELEASE}" != REPLACE_* && "${RELEASE}" != "dev" ]] ||
    die "replace the SALTACODE_RELEASE placeholder with an immutable tag"

  FRONTEND_PORT="${SALTACODE_FRONTEND_PORT:-$(env_value SALTACODE_FRONTEND_PORT "${ENV_FILE}")}"
  BACKEND_PORT="${SALTACODE_BACKEND_PORT:-$(env_value SALTACODE_BACKEND_PORT "${ENV_FILE}")}"
  REDIS_IMAGE="${SALTACODE_REDIS_IMAGE:-$(env_value SALTACODE_REDIS_IMAGE "${ENV_FILE}")}"
  FRONTEND_PORT="${FRONTEND_PORT:-18080}"
  BACKEND_PORT="${BACKEND_PORT:-18081}"
  [[ "${FRONTEND_PORT}" =~ ^[0-9]+$ && "${BACKEND_PORT}" =~ ^[0-9]+$ ]] ||
    die "origin ports must be numeric"
  (( FRONTEND_PORT >= 1024 && FRONTEND_PORT <= 65535 )) || die "invalid frontend port"
  (( BACKEND_PORT >= 1024 && BACKEND_PORT <= 65535 )) || die "invalid backend port"

  COMPOSE_ARGS=(
    --project-directory "${PROJECT_ROOT}"
    --env-file "${ENV_FILE}"
    -f "${PROJECT_ROOT}/compose.yml"
  )
  if [[ "${DEPLOY_ENV}" == "sandbox" ]]; then
    COMPOSE_ARGS+=( -f "${PROJECT_ROOT}/compose.sandbox.yml" )
  fi

  export SALTACODE_RELEASE="${RELEASE}"
  export SALTACODE_FRONTEND_PORT="${FRONTEND_PORT}"
  export SALTACODE_BACKEND_PORT="${BACKEND_PORT}"
  if [[ -n "${REDIS_IMAGE}" ]]; then
    export SALTACODE_REDIS_IMAGE="${REDIS_IMAGE}"
  fi
}

compose() {
  docker compose "${COMPOSE_ARGS[@]}" "$@"
}

acquire_deploy_lock() {
  STATE_DIR="${SALTACODE_STATE_DIR:-/var/lib/saltacode}"
  [[ -d "${STATE_DIR}" && -w "${STATE_DIR}" ]] ||
    die "state directory must already exist and be writable: ${STATE_DIR}"
  exec 9>"${STATE_DIR}/deploy.lock"
  flock -n 9 || die "another Saltacode deployment holds ${STATE_DIR}/deploy.lock"
}

atomic_write() {
  local destination="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "${destination}.tmp.XXXXXX")"
  printf '%s\n' "${value}" >"${temporary}"
  chmod 0640 "${temporary}"
  mv -f "${temporary}" "${destination}"
}

read_previous_release() {
  local component="$1"
  local file="${STATE_DIR}/current-${component}-release"
  if [[ -r "${file}" ]]; then
    head -n 1 "${file}"
  fi
}

record_release() {
  local component="$1"
  local previous="$2"
  shift 2
  local metadata=("$@")
  local timestamp receipt
  timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
  receipt="${STATE_DIR}/${timestamp}-${component}-${RELEASE}.receipt"

  umask 0027
  {
    printf 'component=%s\n' "${component}"
    printf 'release=%s\n' "${RELEASE}"
    printf 'previous_release=%s\n' "${previous:-none}"
    printf 'deployed_at=%s\n' "${timestamp}"
    printf 'environment=%s\n' "${DEPLOY_ENV}"
    if (( ${#metadata[@]} > 0 )); then
      printf '%s\n' "${metadata[@]}"
    fi
  } >"${receipt}"
  atomic_write "${STATE_DIR}/current-${component}-release" "${RELEASE}"
}

restore_release() {
  local previous="$1"
  shift
  local services=("$@")

  if [[ -z "${previous}" || "${previous}" == "${RELEASE}" ]]; then
    printf 'rollback unavailable: no distinct previous release was recorded\n' >&2
    return 1
  fi

  printf 'restoring %s to release %s\n' "${services[*]}" "${previous}" >&2
  SALTACODE_RELEASE="${previous}" compose up -d --wait --no-deps "${services[@]}"
}
