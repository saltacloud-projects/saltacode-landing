#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/../lib.sh"

PREVIOUS_FRONTEND_IMAGE_ID=unexpected
PREVIOUS_BACKEND_IMAGE_ID=unexpected
PREVIOUS_REDIS_IMAGE_ID=unexpected

assert_site_restore_point "" ""

[[ "${PREVIOUS_FRONTEND_IMAGE_ID}" == "none" ]]
[[ "${PREVIOUS_BACKEND_IMAGE_ID}" == "none" ]]
[[ "${PREVIOUS_REDIS_IMAGE_ID}" == "none" ]]

temporary_directory="$(mktemp -d)"
trap 'rm -rf -- "${temporary_directory}"' EXIT
fixture="${temporary_directory}/site.env"
cat >"${fixture}" <<EOF
SALTACODE_RELEASE=build-network-test
SALTACODE_AGENT_ROUTE_KEY=test-route
SALTACODE_REDIS_IMAGE=redis:7.4-alpine@sha256:$(printf 'a%.0s' {1..64})
SALTACODE_AGENT_INTERNAL_TOKEN_SOURCE_FILE=${temporary_directory}/agent-token
SALTACODE_SESSION_SIGNING_SECRET_SOURCE_FILE=${temporary_directory}/session-secret
EOF

configure_fixture() {
  unset SALTACODE_ENV_FILE SALTACODE_RELEASE SALTACODE_BUILD_NETWORK
  export SALTACODE_DEPLOY_ENV=sandbox
  if [[ -n "${1:-}" ]]; then
    export SALTACODE_BUILD_NETWORK="$1"
  fi
  configure_environment "${fixture}"
}

default_hash="$(
  configure_fixture
  [[ "${BUILD_NETWORK}" == "default" && "${SALTACODE_BUILD_NETWORK}" == "default" ]] ||
    die "missing build network did not resolve to default"
  environment_contract_hash
)"
host_hash="$(
  configure_fixture host
  [[ "${BUILD_NETWORK}" == "host" && "${SALTACODE_BUILD_NETWORK}" == "host" ]] ||
    die "host build network override was not exported"
  environment_contract_hash
)"
[[ "${default_hash}" != "${host_hash}" ]]

printf 'SALTACODE_BUILD_NETWORK=host\n' >>"${fixture}"
(
  configure_fixture
  [[ "${BUILD_NETWORK}" == "host" ]]
)
(
  configure_fixture default
  [[ "${BUILD_NETWORK}" == "default" ]]
)
for invalid in none bridge HOST 'host;true'; do
  if (configure_fixture "${invalid}") >"${temporary_directory}/invalid.log" 2>&1; then
    die "unsupported build network was accepted: ${invalid}"
  fi
  grep -q 'SALTACODE_BUILD_NETWORK must be default or host' \
    "${temporary_directory}/invalid.log"
done

sed -i 's/SALTACODE_BUILD_NETWORK=host/SALTACODE_BUILD_NETWORK=bridge/' "${fixture}"
if (configure_fixture) >"${temporary_directory}/invalid.log" 2>&1; then
  die "unsupported build network from environment file was accepted"
fi
grep -q 'SALTACODE_BUILD_NETWORK must be default or host' \
  "${temporary_directory}/invalid.log"

for mode in default host; do
  (
    configure_fixture "${mode}"
    compose config --format json >"${temporary_directory}/${mode}.json"
  )
done
python3 - "${temporary_directory}/default.json" "${temporary_directory}/host.json" <<'PY'
import json
import sys
from pathlib import Path

models = [json.loads(Path(path).read_text()) for path in sys.argv[1:]]
for model, mode in zip(models, ("default", "host")):
    for service in ("frontend", "backend"):
        assert model["services"][service]["build"].pop("network") == mode
assert models[0] == models[1], "build network override changed the runtime contract"
PY

printf 'site release-lib first-release and build-network tests passed\n'
