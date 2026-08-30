#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  printf '[FAIL][required] python3: command not found\n' >&2
  exit 1
fi

exec python3 "${repo_root}/scripts/agentic/doctor.py" "${repo_root}"
