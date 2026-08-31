#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=release-lib.sh
source "${SCRIPT_DIR}/../release-lib.sh"

first_override="$(mktemp)"
second_override="$(mktemp)"
trap 'rm -f -- "${first_override}" "${second_override}"' EXIT

printf '%s\n' 'secrets: {}' >"${first_override}"
cp -- "${first_override}" "${second_override}"

first_hash="$(compose_contract_sha256 "${COMPOSE_FILE}" "${first_override}")"
second_hash="$(compose_contract_sha256 "${COMPOSE_FILE}" "${second_override}")"
[[ "${first_hash}" == "${second_hash}" ]] || {
  printf 'error: identical Compose content produced path-dependent hashes\n' >&2
  exit 1
}

printf '%s\n' 'services: {}' >>"${second_override}"
changed_hash="$(compose_contract_sha256 "${COMPOSE_FILE}" "${second_override}")"
[[ "${first_hash}" != "${changed_hash}" ]] || {
  printf 'error: changed Compose content did not change the contract hash\n' >&2
  exit 1
}

printf 'release-lib Compose contract hash tests passed\n'
