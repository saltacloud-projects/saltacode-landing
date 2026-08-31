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
  FRONTEND_BIND_ADDRESS="${SALTACODE_FRONTEND_BIND_ADDRESS:-$(env_value SALTACODE_FRONTEND_BIND_ADDRESS "${ENV_FILE}")}"
  BACKEND_BIND_ADDRESS="${SALTACODE_BACKEND_BIND_ADDRESS:-$(env_value SALTACODE_BACKEND_BIND_ADDRESS "${ENV_FILE}")}"
  ALLOWED_ORIGINS="${SALTACODE_ALLOWED_ORIGINS:-$(env_value SALTACODE_ALLOWED_ORIGINS "${ENV_FILE}")}"
  REDIS_IMAGE="${SALTACODE_REDIS_IMAGE:-$(env_value SALTACODE_REDIS_IMAGE "${ENV_FILE}")}"
  FRONTEND_PORT="${FRONTEND_PORT:-18080}"
  BACKEND_PORT="${BACKEND_PORT:-18081}"
  FRONTEND_BIND_ADDRESS="${FRONTEND_BIND_ADDRESS:-127.0.0.1}"
  BACKEND_BIND_ADDRESS="${BACKEND_BIND_ADDRESS:-127.0.0.1}"
  ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-http://localhost:${FRONTEND_PORT}}"
  if [[ "${DEPLOY_ENV}" == "production" ]]; then
    default_frontend_backend_subnet="10.248.244.32/28"
    default_rate_limit_subnet="10.248.244.48/28"
    default_ingress_subnet="10.248.244.64/28"
  else
    default_frontend_backend_subnet="10.248.242.32/28"
    default_rate_limit_subnet="10.248.242.48/28"
    default_ingress_subnet="10.248.242.64/28"
  fi
  FRONTEND_BACKEND_SUBNET="${SALTACODE_FRONTEND_BACKEND_SUBNET:-$(env_value SALTACODE_FRONTEND_BACKEND_SUBNET "${ENV_FILE}")}"
  RATE_LIMIT_SUBNET="${SALTACODE_RATE_LIMIT_SUBNET:-$(env_value SALTACODE_RATE_LIMIT_SUBNET "${ENV_FILE}")}"
  INGRESS_SUBNET="${SALTACODE_INGRESS_SUBNET:-$(env_value SALTACODE_INGRESS_SUBNET "${ENV_FILE}")}"
  FRONTEND_BACKEND_SUBNET="${FRONTEND_BACKEND_SUBNET:-${default_frontend_backend_subnet}}"
  RATE_LIMIT_SUBNET="${RATE_LIMIT_SUBNET:-${default_rate_limit_subnet}}"
  INGRESS_SUBNET="${INGRESS_SUBNET:-${default_ingress_subnet}}"
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
  export SALTACODE_FRONTEND_BIND_ADDRESS="${FRONTEND_BIND_ADDRESS}"
  export SALTACODE_BACKEND_BIND_ADDRESS="${BACKEND_BIND_ADDRESS}"
  export SALTACODE_ALLOWED_ORIGINS="${ALLOWED_ORIGINS}"
  export SALTACODE_FRONTEND_BACKEND_SUBNET="${FRONTEND_BACKEND_SUBNET}"
  export SALTACODE_RATE_LIMIT_SUBNET="${RATE_LIMIT_SUBNET}"
  export SALTACODE_INGRESS_SUBNET="${INGRESS_SUBNET}"
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

effective_env_value() {
  local key="$1"
  local fallback="${2:-}"
  local value
  if [[ -v "${key}" ]]; then
    value="${!key}"
  else
    value="$(env_value "${key}" "${ENV_FILE}")"
  fi
  printf '%s' "${value:-${fallback}}"
}

sha256_text() {
  require_command sha256sum
  sha256sum | awk '{print $1}'
}

header_value() {
  local file="$1"
  local wanted="$2"
  awk -F: -v wanted="${wanted}" '
    tolower($1) == tolower(wanted) {
      sub(/^[^:]*:[[:space:]]*/, "")
      sub(/\r$/, "")
      print
      exit
    }
  ' "${file}"
}

verify_security_headers() {
  local headers="$1"
  local require_hsts="${2:-no}"
  local csp hsts max_age

  csp="$(header_value "${headers}" Content-Security-Policy)"
  [[ "${csp}" == *"default-src 'self'"* && "${csp}" == *"frame-ancestors 'none'"* ]] ||
    die "response CSP is missing the default-src or frame-ancestors boundary"
  [[ "$(header_value "${headers}" X-Content-Type-Options)" == "nosniff" ]] ||
    die "response is missing X-Content-Type-Options: nosniff"
  [[ "$(header_value "${headers}" X-Frame-Options)" == "DENY" ]] ||
    die "response is missing X-Frame-Options: DENY"
  [[ "$(header_value "${headers}" Referrer-Policy)" == "strict-origin-when-cross-origin" ]] ||
    die "response has an unexpected Referrer-Policy"
  [[ -n "$(header_value "${headers}" Permissions-Policy)" ]] ||
    die "response is missing Permissions-Policy"

  if [[ "${require_hsts}" == "yes" ]]; then
    hsts="$(header_value "${headers}" Strict-Transport-Security)"
    max_age="$(sed -nE 's/.*max-age=([0-9]+).*/\1/ip' <<<"${hsts}")"
    [[ "${max_age}" =~ ^[0-9]+$ ]] || die "public response is missing valid HSTS"
    (( max_age >= 31536000 )) || die "public HSTS max-age must be at least one year"
  fi
}

verify_chat_contract_canary() {
  local base="$1"
  local origin="$2"
  local output_prefix="$3"
  local user_agent="${4:-Saltacode-Release-Canary/1.0}"
  local status content_type

  # Deliberately use a valid but unsupported privacy version. The BFF rejects it
  # before rate limiting, session creation, persistence, or agent invocation.
  status="$(curl --silent --show-error --max-time 20 \
    --output "${output_prefix}.body" \
    --dump-header "${output_prefix}.headers" \
    --write-out '%{http_code}' \
    --request POST \
    --user-agent "${user_agent}" \
    --header "Origin: ${origin}" \
    --header 'Content-Type: application/json' \
    --data '{"client_message_id":"00000000-0000-4000-8000-000000000001","message":"release-canary","locale":"es-AR","transcript_consent":true,"privacy_version":"release-canary-unsupported"}' \
    "${base}/api/v1/chat")"
  [[ "${status}" == "400" ]] || die "chat contract canary expected HTTP 400, got ${status}"
  content_type="$(header_value "${output_prefix}.headers" Content-Type)"
  [[ "${content_type}" == application/problem+json* ]] ||
    die "chat contract canary did not return application/problem+json"
  grep -Eq '"code"[[:space:]]*:[[:space:]]*"privacy_version_unsupported"' \
    "${output_prefix}.body" || die "chat contract canary returned the wrong problem code"
  [[ -z "$(header_value "${output_prefix}.headers" Set-Cookie)" ]] ||
    die "chat contract canary unexpectedly created a browser session"
}

git_sha() {
  git -C "${PROJECT_ROOT}" rev-parse HEAD
}

git_short_sha() {
  git -C "${PROJECT_ROOT}" rev-parse --short=12 HEAD
}

assert_release_identity() {
  local sha short status
  require_command git
  sha="$(git_sha)"
  short="$(git_short_sha)"
  if [[ "${DEPLOY_ENV}" == "production" ]]; then
    [[ "${RELEASE}" =~ ^git-${short}-[0-9]{8}T[0-9]{6}Z$ ]] ||
      die "production SALTACODE_RELEASE must be git-${short}-YYYYMMDDTHHMMSSZ"
    status="$(git -C "${PROJECT_ROOT}" status --porcelain=v1 --untracked-files=normal)"
    [[ -z "${status}" ]] || die "production release requires a clean Git worktree"
  fi
  RELEASE_GIT_SHA="${sha}"
  export RELEASE_GIT_SHA
}

environment_contract_hash() {
  local keys key
  keys=(
    SALTACODE_RELEASE
    SALTACODE_FRONTEND_BIND_ADDRESS
    SALTACODE_FRONTEND_PORT
    SALTACODE_BACKEND_BIND_ADDRESS
    SALTACODE_BACKEND_PORT
    SALTACODE_FRONTEND_BACKEND_SUBNET
    SALTACODE_RATE_LIMIT_SUBNET
    SALTACODE_INGRESS_SUBNET
    SALTACODE_APP_ENV
    SALTACODE_ALLOWED_ORIGINS
    SALTACODE_SECRET_GID
    SALTACODE_AGENT_ROUTE_KEY
    SALTACODE_RATE_LIMIT_BACKEND
    SALTACODE_REDIS_URL
    SALTACODE_REDIS_IMAGE
    SALTACODE_REDIS_UID
    SALTACODE_REDIS_GID
    SALTACODE_RATE_LIMIT_REQUESTS
    SALTACODE_RATE_LIMIT_WINDOW_SECONDS
  )
  for key in "${keys[@]}"; do
    printf '%s=%s\n' "${key}" "$(effective_env_value "${key}")"
  done | LC_ALL=C sort | sha256_text
}

compose_contract_hash() {
  compose config | sha256_text
}

validate_network_contract() {
  local project_name
  local network_ids=()
  require_command python3
  project_name="saltacode"
  [[ "${DEPLOY_ENV}" == "sandbox" ]] && project_name="saltacode-sandbox"
  mapfile -t network_ids < <(docker network ls --quiet)

  if (( ${#network_ids[@]} > 0 )); then
    # Ignore this Compose project's own networks so a normal redeploy is idempotent.
    # Every other existing Docker subnet is an exclusion boundary.
    docker network inspect "${network_ids[@]}" | python3 -c '
import ipaddress
import json
import sys

project, *desired_values = sys.argv[1:]
desired = [ipaddress.ip_network(value, strict=True) for value in desired_values]
desired_by_name = dict(zip(("frontend_backend", "rate_limit", "ingress"), desired))
for index, subnet in enumerate(desired):
    if any(subnet.overlaps(other) for other in desired[index + 1:]):
        raise SystemExit(f"configured site subnets overlap: {subnet}")

for network in json.load(sys.stdin):
    labels = network.get("Labels") or {}
    same_project = labels.get("com.docker.compose.project") == project
    contract_name = labels.get("com.docker.compose.network")
    name = network.get("Name", "unknown")
    for config in (network.get("IPAM") or {}).get("Config") or []:
        existing_value = config.get("Subnet")
        if not existing_value:
            continue
        existing = ipaddress.ip_network(existing_value, strict=False)
        if same_project and contract_name in {"frontend_backend", "rate_limit", "ingress"}:
            if existing == desired_by_name[contract_name]:
                continue
            raise SystemExit(
                f"existing {project} network {name} has contract drift ({existing})"
            )
        if same_project:
            continue
        for subnet in desired:
            if subnet.version == existing.version and subnet.overlaps(existing):
                raise SystemExit(
                    f"configured subnet {subnet} overlaps Docker network {name} ({existing})"
                )
' "${project_name}" "${FRONTEND_BACKEND_SUBNET}" "${RATE_LIMIT_SUBNET}" "${INGRESS_SUBNET}" ||
      die "site Docker network contract is not available"
    return
  fi

  python3 -c '
import ipaddress
import sys
values = [ipaddress.ip_network(value, strict=True) for value in sys.argv[1:]]
for index, subnet in enumerate(values):
    if any(subnet.overlaps(other) for other in values[index + 1:]):
        raise SystemExit(f"configured site subnets overlap: {subnet}")
' "${FRONTEND_BACKEND_SUBNET}" "${RATE_LIMIT_SUBNET}" "${INGRESS_SUBNET}" ||
    die "site Docker network contract is invalid"
}

image_id() {
  docker image inspect --format '{{.Id}}' "$1" 2>/dev/null
}

running_service_image_id() {
  local container
  container="$(compose ps --quiet "$1")"
  [[ -n "${container}" ]] || die "service $1 has no running container"
  docker inspect --format '{{.Image}}' "${container}"
}

assert_site_release_tag_available() {
  local receipt reference
  while IFS= read -r -d '' receipt; do
    if grep -Fqx "release=${RELEASE}" "${receipt}"; then
      die "release tag ${RELEASE} already has a site receipt and cannot be reused"
    fi
  done < <(find "${STATE_DIR}" -maxdepth 1 -type f -name '*-site-*.receipt' -print0)

  for reference in \
    "localhost/saltacode/frontend:${RELEASE}" \
    "localhost/saltacode/backend:${RELEASE}"; do
    if docker image inspect "${reference}" >/dev/null 2>&1; then
      die "release image tag already exists and cannot be rebuilt: ${reference}"
    fi
  done
}

receipt_field() {
  local key="$1"
  local receipt="$2"
  awk -F= -v wanted="${key}" '$1 == wanted {sub(/^[^=]*=/, ""); print; exit}' "${receipt}"
}

assert_site_restore_point() {
  local previous="$1"
  local previous_redis="$2"
  local pointer receipt expected actual

  PREVIOUS_FRONTEND_IMAGE_ID=none
  PREVIOUS_BACKEND_IMAGE_ID=none
  PREVIOUS_REDIS_IMAGE_ID=none
  [[ -n "${previous}" ]] || return 0
  [[ -n "${previous_redis}" ]] || die "previous site release has no recorded Redis image"

  PREVIOUS_FRONTEND_IMAGE_ID="$(image_id "localhost/saltacode/frontend:${previous}")"
  PREVIOUS_BACKEND_IMAGE_ID="$(image_id "localhost/saltacode/backend:${previous}")"
  PREVIOUS_REDIS_IMAGE_ID="$(image_id "${previous_redis}")"
  [[ -n "${PREVIOUS_FRONTEND_IMAGE_ID}" && -n "${PREVIOUS_BACKEND_IMAGE_ID}" &&
     -n "${PREVIOUS_REDIS_IMAGE_ID}" ]] ||
    die "previous site release ${previous} is not restorable from local immutable images"

  pointer="${STATE_DIR}/current-site-receipt"
  if [[ -r "${pointer}" ]]; then
    receipt="$(head -n 1 "${pointer}")"
    [[ "$(dirname -- "${receipt}")" == "${STATE_DIR}" ]] ||
      die "current site receipt must stay inside ${STATE_DIR}"
    [[ -r "${receipt}" ]] || die "current site receipt is unreadable: ${receipt}"
    [[ -r "${receipt}.sha256" ]] || die "current site receipt checksum is unreadable"
    (cd "${STATE_DIR}" && sha256sum --check --status "$(basename "${receipt}").sha256") ||
      die "current site receipt checksum does not match"
    [[ "$(receipt_field release "${receipt}")" == "${previous}" ]] ||
      die "current site receipt does not match release ${previous}"
    for key in frontend_image_id backend_image_id redis_image_id; do
      expected="$(receipt_field "${key}" "${receipt}")"
      case "${key}" in
        frontend_image_id) actual="${PREVIOUS_FRONTEND_IMAGE_ID}" ;;
        backend_image_id) actual="${PREVIOUS_BACKEND_IMAGE_ID}" ;;
        redis_image_id) actual="${PREVIOUS_REDIS_IMAGE_ID}" ;;
      esac
      [[ -n "${expected}" && "${expected}" == "${actual}" ]] ||
        die "restore image identity mismatch for ${key}"
    done
  fi
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
  local timestamp receipt checksum entry
  timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
  receipt="${STATE_DIR}/${timestamp}-${component}-${RELEASE}.receipt"

  umask 0027
  for entry in "${metadata[@]}"; do
    [[ "${entry}" != *$'\n'* && "${entry}" == *=* ]] ||
      die "release receipt metadata must be single-line key=value entries"
  done

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
  chmod 0440 "${receipt}"
  checksum="$(sha256sum "${receipt}" | awk '{print $1}')"
  atomic_write "${receipt}.sha256" "${checksum}  $(basename "${receipt}")"
  atomic_write "${STATE_DIR}/current-${component}-release" "${RELEASE}"
  atomic_write "${STATE_DIR}/current-${component}-receipt" "${receipt}"
  LAST_RELEASE_RECEIPT="${receipt}"
  export LAST_RELEASE_RECEIPT
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
  SALTACODE_RELEASE="${previous}" compose up -d --wait --no-build --no-deps "${services[@]}"
}
