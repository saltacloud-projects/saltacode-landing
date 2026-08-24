#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

configure_environment "${1:-}"
require_command curl

temporary="$(mktemp -d)"
trap 'rm -rf "${temporary}"' EXIT

front="http://127.0.0.1:${FRONTEND_PORT}"
back="http://127.0.0.1:${BACKEND_PORT}"

curl --fail --silent --show-error --max-time 5 "${front}/healthz" >/dev/null
curl --fail --silent --show-error --max-time 10 "${front}/" >"${temporary}/index.html"
curl --fail --silent --show-error --max-time 5 "${front}/robots.txt" >"${temporary}/robots.txt"
curl --fail --silent --show-error --max-time 5 "${front}/sitemap.xml" >"${temporary}/sitemap.xml"
curl --fail --silent --show-error --max-time 5 "${back}/health/live" >/dev/null
curl --fail --silent --show-error --max-time 5 "${back}/health/ready" >/dev/null
[[ "$(compose exec -T redis redis-cli -h 127.0.0.1 ping)" == "PONG" ]] ||
  die "private Redis rate limiter did not answer PONG"

grep -Eqi '<link[^>]+rel="canonical"[^>]+href="https://saltacode\.com\.ar/?"' \
  "${temporary}/index.html" || die "local homepage canonical is missing or not the apex HTTPS URL"
grep -Fq 'Sitemap: https://saltacode.com.ar/sitemap.xml' "${temporary}/robots.txt" ||
  die "robots.txt does not advertise the canonical sitemap"
grep -Fq '<loc>https://saltacode.com.ar/' "${temporary}/sitemap.xml" ||
  die "sitemap does not contain the canonical homepage"

missing_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
  "${front}/__saltacode_missing_${RANDOM}")"
[[ "${missing_status}" == "404" ]] || die "static origin must return a real 404, got ${missing_status}"

if command -v ss >/dev/null 2>&1; then
  for port in "${FRONTEND_PORT}" "${BACKEND_PORT}"; do
    listeners="$(ss -H -ltn "sport = :${port}" || true)"
    [[ -n "${listeners}" ]] || die "no local listener found on port ${port}"
    if grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\*|\[::\]):' <<<"${listeners}"; then
      die "origin port ${port} is exposed beyond loopback"
    fi
  done
fi

printf 'local verification passed: frontend=%s backend=%s\n' "${front}" "${back}"
