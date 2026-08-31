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

printf 'site release-lib first-release tests passed\n'
