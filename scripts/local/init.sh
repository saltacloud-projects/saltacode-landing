#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
agent_root="${root}/agent-platform"
cd "$root"
"$agent_root/scripts/platform/init-local-secrets.sh"
umask 077
mkdir -p secrets
[[ -s secrets/session_signing_secret ]] || openssl rand -hex 32 > secrets/session_signing_secret
lan_ip="$(hostname -I | awk '{print $1}')"
cat > .env.sandbox.local <<ENV
SALTACODE_RELEASE=sandbox
SALTACODE_FRONTEND_BIND_ADDRESS=0.0.0.0
SALTACODE_FRONTEND_PORT=28080
SALTACODE_BACKEND_BIND_ADDRESS=0.0.0.0
SALTACODE_BACKEND_PORT=28081
SALTACODE_APP_ENV=development
SALTACODE_ALLOWED_ORIGINS=http://localhost:28080,http://127.0.0.1:28080,http://${lan_ip}:28080
SALTACODE_AGENT_INTERNAL_TOKEN_SOURCE_FILE=${agent_root}/.secrets/internal_api_token
SALTACODE_AGENT_ROUTE_KEY=saltacode-landing
SALTACODE_SESSION_SIGNING_SECRET_SOURCE_FILE=${root}/secrets/session_signing_secret
SALTACODE_RATE_LIMIT_BACKEND=redis
SALTACODE_REDIS_URL=redis://redis:6379/0
SALTACODE_REDIS_IMAGE=redis:7.4.2-alpine@sha256:02419de7eddf55aa5bcf49efb74e88fa8d931b4d77c07eff8a6b2144472b6952
SALTACODE_REDIS_UID=999
SALTACODE_REDIS_GID=1000
SALTACODE_RATE_LIMIT_REQUESTS=100
SALTACODE_RATE_LIMIT_WINDOW_SECONDS=60
ENV
chmod 600 .env.sandbox.local
chmod 640 secrets/session_signing_secret
echo "Local Saltacode configuration is ready."
