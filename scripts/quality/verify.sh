#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

scope="${1:-all}"
test_postgres_container=""
temporary_directory=""
site_env_fixture=""
agent_env_fixture=""
agent_compose_override_fixture=""

cleanup() {
  if [[ -n "${test_postgres_container}" ]]; then
    docker rm -f "${test_postgres_container}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${temporary_directory}" ]]; then
    rm -rf "${temporary_directory}"
  fi
}
trap cleanup EXIT

section() {
  printf '\n==> %s\n' "$1"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'ERROR: required command not found: %s\n' "$1" >&2
    exit 1
  }
}

verify_frontend() {
  section "Frontend"
  require_command pnpm
  pnpm --filter @saltacode/frontend check
  pnpm --filter @saltacode/frontend test
}

verify_backend() {
  section "Backend"
  require_command uv
  (
    cd backend
    uv run --locked ruff format --check .
    uv run --locked ruff check .
    uv run --locked pytest
    uv run --locked python scripts/export_contracts.py --check
  )
}

start_test_postgres() {
  require_command docker
  test_postgres_container="saltacode-agent-tests-${RANDOM}-$$"

  docker run --detach --rm \
    --name "${test_postgres_container}" \
    --env POSTGRES_DB=test \
    --env POSTGRES_USER=test \
    --env POSTGRES_PASSWORD=test \
    --publish 127.0.0.1::5432 \
    pgvector/pgvector:0.8.3-pg16-trixie >/dev/null

  local postgres_port
  postgres_port="$(docker port "${test_postgres_container}" 5432/tcp | awk -F: 'NR == 1 {print $NF}')"
  [[ "${postgres_port}" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: could not determine the agent test PostgreSQL port\n' >&2
    exit 1
  }

  local attempt
  for attempt in $(seq 1 30); do
    if docker exec "${test_postgres_container}" pg_isready -U test -d test >/dev/null 2>&1; then
      export AGENT_TEST_POSTGRES_DSN="postgresql+asyncpg://test:test@127.0.0.1:${postgres_port}/test"
      return
    fi
    sleep 1
  done

  printf 'ERROR: agent test PostgreSQL did not become ready\n' >&2
  docker logs "${test_postgres_container}" >&2 || true
  exit 1
}

verify_agent_api() {
  section "Agent API"
  require_command uv

  if [[ -z "${AGENT_TEST_POSTGRES_DSN:-}" ]]; then
    start_test_postgres
  fi

  (
    cd agent-platform/fastapi
    export FASTAPI_ENV=testing
    export FASTAPI_API_KEY="quality-gate-internal-token"
    export JWT_SECRET_KEY="quality-gate-jwt-secret-at-least-32-characters"
    export POSTGRES_DSN="${AGENT_TEST_POSTGRES_DSN}"
    export ADMIN_INITIAL_EMAIL="quality-gate-admin@example.invalid"
    export ADMIN_INITIAL_PASSWORD="quality-gate-admin-password"
    export DEFAULT_AGENT_SLUG="saltacode"
    export AGENT_WEB_ROUTE_KEY="saltacode-landing"
    export OPENAI_API_KEY="quality-gate-openai-key"
    export WHATSAPP_TOKEN=""
    export WHATSAPP_PHONE_NUMBER_ID=""
    export WHATSAPP_VERIFY_TOKEN=""
    export WHATSAPP_APP_SECRET=""
    uv run --locked alembic -c alembic-platform.ini upgrade head
    uv run --locked alembic -c alembic-platform.ini check
    uv run --locked ruff format --check app tests
    uv run --locked ruff check app tests
    uv run --locked pip-audit --strict
    uv run --locked pytest -o addopts='' -m 'not integration'
    export OPENAI_API_KEY=""
    uv run --locked python -m app.bootstrap
    uv run --locked pytest -o addopts='' -m integration
  )
}

verify_agent_panel() {
  section "Agent administration panel"
  require_command npm
  (
    cd agent-platform/frontend
    if [[ -z "${PLAYWRIGHT_CHROME_PATH:-}" ]]; then
      local playwright_browser
      playwright_browser="$(node -e "const { chromium } = require('playwright'); process.stdout.write(chromium.executablePath())" 2>/dev/null || true)"
      if [[ -x "${playwright_browser}" ]]; then
        export PLAYWRIGHT_CHROME_PATH="${playwright_browser}"
      fi
    fi
    npm run check
    npm run build
    npm run test:e2e
    npm audit --audit-level=moderate
  )
}

write_compose_fixture() {
  temporary_directory="$(mktemp -d)"
  local token_file="${temporary_directory}/agent-internal-token"
  local session_file="${temporary_directory}/session-signing-secret"
  local source_master_file="${temporary_directory}/source-master-key"
  local site_env="${temporary_directory}/site.env"
  local agent_env="${temporary_directory}/agent.env"
  local agent_compose_override="${temporary_directory}/agent-compose.override.yml"
  local agent_state_dir="${temporary_directory}/agent-state"

  printf '%s\n' 'quality-gate-agent-token-at-least-32-characters' >"${token_file}"
  printf '%s\n' 'quality-gate-session-secret-at-least-32-characters' >"${session_file}"
  printf '%s\n' 'quality-gate-source-master-key-at-least-32-characters' >"${source_master_file}"
  chmod 0640 "${token_file}" "${session_file}" "${source_master_file}"
  mkdir -m 0750 "${agent_state_dir}"
  local secret_gid
  secret_gid="$(stat -c '%g' "${token_file}")"

  cat >"${site_env}" <<EOF
SALTACODE_RELEASE=quality-gate
SALTACODE_FRONTEND_BIND_ADDRESS=127.0.0.1
SALTACODE_FRONTEND_PORT=18080
SALTACODE_BACKEND_BIND_ADDRESS=127.0.0.1
SALTACODE_BACKEND_PORT=18081
SALTACODE_APP_ENV=production
SALTACODE_ALLOWED_ORIGINS=https://saltacode.com.ar
SALTACODE_AGENT_INTERNAL_TOKEN_SOURCE_FILE=${token_file}
SALTACODE_SESSION_SIGNING_SECRET_SOURCE_FILE=${session_file}
SALTACODE_SECRET_GID=${secret_gid}
SALTACODE_AGENT_ROUTE_KEY=saltacode-landing
SALTACODE_RATE_LIMIT_BACKEND=redis
SALTACODE_REDIS_URL=redis://redis:6379/0
SALTACODE_REDIS_IMAGE=redis:7.4-alpine@sha256:0000000000000000000000000000000000000000000000000000000000000000
SALTACODE_REDIS_UID=999
SALTACODE_REDIS_GID=999
SALTACODE_RATE_LIMIT_REQUESTS=20
SALTACODE_RATE_LIMIT_WINDOW_SECONDS=60
EOF

  cat >"${agent_env}" <<EOF
APP_VERSION=quality-gate
AGENT_PLATFORM_DEPLOY_ENV=sandbox
AGENT_PLATFORM_STATE_DIR=${agent_state_dir}
AGENT_PLATFORM_INTERNAL_TOKEN_SOURCE_FILE=${token_file}
AGENT_PLATFORM_SOURCE_MASTER_KEY_FILE=${source_master_file}
AGENT_PLATFORM_ENABLE_RAG_WORKER=0
FASTAPI_ENV=testing
POSTGRES_DB=agent_platform
POSTGRES_USER=agent_platform
POSTGRES_PASSWORD=quality-gate-postgres-password
JWT_SECRET_KEY=quality-gate-jwt-secret-at-least-32-characters
ADMIN_INITIAL_EMAIL=admin@example.invalid
ADMIN_INITIAL_PASSWORD=quality-gate-admin-password
EOF
  chmod 0640 "${site_env}" "${agent_env}"

  cat >"${agent_compose_override}" <<EOF
secrets:
  internal_api_token:
    file: ${token_file}
  source_master_key:
    file: ${source_master_file}
EOF

  site_env_fixture="${site_env}"
  agent_env_fixture="${agent_env}"
  agent_compose_override_fixture="${agent_compose_override}"
}

verify_infrastructure() {
  section "Shell and Compose infrastructure"
  require_command docker

  while IFS= read -r -d '' script; do
    bash -n "${script}"
  done < <(
    find infrastructure/scripts scripts/agentic scripts/local scripts/quality \
      agent-platform/scripts -type f -name '*.sh' -print0
  )

  write_compose_fixture

  docker compose --env-file "${site_env_fixture}" -f compose.yml config --quiet
  docker compose --env-file "${site_env_fixture}" \
    -f compose.yml -f compose.sandbox.yml config --quiet
  docker compose --env-file "${agent_env_fixture}" \
    -f agent-platform/docker-compose.yml \
    -f "${agent_compose_override_fixture}" config --quiet
  AGENT_PLATFORM_ENV_FILE="${agent_env_fixture}" \
    agent-platform/scripts/platform/preflight-release.sh
}

verify_agentic() {
  section "Agentic contracts"
  require_command python3
  python3 -m unittest discover -s scripts/agentic/tests -v
  bash scripts/agentic/validate-layer.sh
  bash scripts/agentic/validate-commits.sh --commits HEAD
}

case "${scope}" in
  all)
    verify_frontend
    verify_backend
    verify_agent_api
    verify_agent_panel
    verify_infrastructure
    verify_agentic
    ;;
  frontend) verify_frontend ;;
  backend) verify_backend ;;
  agent-api) verify_agent_api ;;
  agent-panel) verify_agent_panel ;;
  infrastructure) verify_infrastructure ;;
  agentic) verify_agentic ;;
  *)
    printf 'ERROR: unknown verification scope: %s\n' "${scope}" >&2
    printf 'Expected: all, frontend, backend, agent-api, agent-panel, infrastructure, agentic\n' >&2
    exit 2
    ;;
esac

printf '\nQuality verification passed: %s\n' "${scope}"
