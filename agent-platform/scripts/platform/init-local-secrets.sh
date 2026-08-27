#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
umask 077
mkdir -p .secrets
read_env_value() {
  local key="$1"
  [[ -f .env.platform.local ]] || return 0
  sed -n "s/^${key}=//p" .env.platform.local | head -n 1
}
write_secret() {
  local file="$1"
  local env_key="${2:-}"
  local value=""
  [[ -s "$file" ]] && return
  [[ -n "$env_key" ]] && value="$(read_env_value "$env_key")"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value" > "$file"
  else
    openssl rand -hex 32 > "$file"
  fi
}
assert_secret_matches_env() {
  local env_key="$1"
  local file="$2"
  local value="$(read_env_value "$env_key")"
  if [[ -n "$value" && "$value" != "$(cat "$file")" ]]; then
    echo "${env_key} does not match ${file}; refusing to start with split credentials." >&2
    exit 1
  fi
}
write_secret .secrets/internal_api_token FASTAPI_API_KEY
write_secret .secrets/jwt_secret JWT_SECRET_KEY
write_secret .secrets/postgres_password POSTGRES_PASSWORD
write_secret .secrets/admin_password ADMIN_INITIAL_PASSWORD
write_secret .secrets/source_seed
if [[ ! -s .secrets/source_master.key ]]; then
  SOURCE_SEED="$(cat .secrets/source_seed)" python - <<'PY'
import base64, hashlib, os
from pathlib import Path
Path('.secrets/source_master.key').write_bytes(base64.urlsafe_b64encode(hashlib.sha256(os.environ['SOURCE_SEED'].encode()).digest()))
PY
fi
if [[ ! -f .env.platform.local ]]; then
  cat > .env.platform.local <<ENV
APP_VERSION=dev
FASTAPI_ENV=development
LOG_LEVEL=INFO
POSTGRES_DB=agent_platform
POSTGRES_USER=agent_platform
POSTGRES_PASSWORD=$(cat .secrets/postgres_password)
REDIS_MAX_MEMORY=256mb
FASTAPI_API_KEY=$(cat .secrets/internal_api_token)
JWT_SECRET_KEY=$(cat .secrets/jwt_secret)
ADMIN_INITIAL_EMAIL=admin@local.saltacode.com
ADMIN_INITIAL_PASSWORD=$(cat .secrets/admin_password)
ADMIN_FRONTEND_URL=http://localhost:23000
DEFAULT_AGENT_SLUG=saltacode
DOMAIN=localhost
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
AGENT_API_BIND_ADDRESS=0.0.0.0
AGENT_API_PORT=28082
AGENT_PANEL_BIND_ADDRESS=0.0.0.0
AGENT_PANEL_PORT=23000
ENV
fi
assert_secret_matches_env FASTAPI_API_KEY .secrets/internal_api_token
assert_secret_matches_env JWT_SECRET_KEY .secrets/jwt_secret
assert_secret_matches_env POSTGRES_PASSWORD .secrets/postgres_password
assert_secret_matches_env ADMIN_INITIAL_PASSWORD .secrets/admin_password
chmod 600 .env.platform.local .secrets/*
chmod 640 .secrets/internal_api_token
echo "Local agent-platform secrets are ready."
