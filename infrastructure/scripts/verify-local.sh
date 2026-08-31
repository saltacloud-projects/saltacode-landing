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
canonical_base="https://saltacode.com.ar"
public_routes=(
  /
  /servicios/
  /servicios/software-a-medida/
  /servicios/consultoria-it/
  /servicios/equipos-it/
  /servicios/productos-saas/
  /nosotros/
  /contacto/
  /legal/privacidad/
  /legal/cookies/
  /legal/terminos/
)

curl --fail --silent --show-error --max-time 5 "${front}/healthz" >/dev/null
curl --fail --silent --show-error --max-time 5 "${back}/health/live" >/dev/null
curl --fail --silent --show-error --max-time 5 "${back}/health/ready" >/dev/null
[[ "$(compose exec -T redis redis-cli -h 127.0.0.1 ping)" == "PONG" ]] ||
  die "private Redis rate limiter did not answer PONG"

for index in "${!public_routes[@]}"; do
  route="${public_routes[${index}]}"
  body="${temporary}/route-${index}.html"
  headers="${temporary}/route-${index}.headers"
  curl --fail --silent --show-error --max-time 10 \
    --header 'X-Forwarded-Proto: https' \
    --dump-header "${headers}" \
    "${front}${route}" >"${body}"
  [[ "$(header_value "${headers}" Content-Type)" == text/html* ]] ||
    die "${route} was not served as HTML"
  grep -Fqi "<link rel=\"canonical\" href=\"${canonical_base}${route}\"" "${body}" ||
    die "${route} has an incorrect canonical URL"
  [[ "$(grep -Eio '<h1([[:space:]][^>]*)?>' "${body}" | wc -l)" == "1" ]] ||
    die "${route} must contain exactly one h1"
  ! grep -Eqi "<meta[^>]+name=[\"']robots[\"'][^>]+noindex" "${body}" ||
    die "${route} unexpectedly declares noindex"
  verify_security_headers "${headers}" no
done

curl --fail --silent --show-error --max-time 5 "${front}/robots.txt" >"${temporary}/robots.txt"
curl --fail --silent --show-error --max-time 5 "${front}/sitemap.xml" >"${temporary}/sitemap.xml"
grep -Fq 'Sitemap: https://saltacode.com.ar/sitemap.xml' "${temporary}/robots.txt" ||
  die "robots.txt does not advertise the canonical sitemap"
for route in "${public_routes[@]}"; do
  grep -Fq "<loc>${canonical_base}${route}</loc>" "${temporary}/sitemap.xml" ||
    die "sitemap is missing ${route}"
done
grep -Eqi 'mailto:' "${temporary}/route-7.html" || die "contact page lost its email path"
grep -Eqi 'https://wa\.me/' "${temporary}/route-7.html" || die "contact page lost its WhatsApp path"

missing_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
  "${front}/__saltacode_missing_${RANDOM}")"
[[ "${missing_status}" == "404" ]] || die "static origin must return a real 404, got ${missing_status}"

chat_origin="${ALLOWED_ORIGINS%%,*}"
chat_origin="${chat_origin#"${chat_origin%%[![:space:]]*}"}"
chat_origin="${chat_origin%"${chat_origin##*[![:space:]]}"}"
[[ -n "${chat_origin}" ]] || die "SALTACODE_ALLOWED_ORIGINS must include a chat canary origin"
verify_chat_contract_canary "${front}" "${chat_origin}" "${temporary}/chat-canary"

if command -v ss >/dev/null 2>&1; then
  binds=(
    "${FRONTEND_BIND_ADDRESS}:${FRONTEND_PORT}"
    "${BACKEND_BIND_ADDRESS}:${BACKEND_PORT}"
  )
  for bind in "${binds[@]}"; do
    port="${bind##*:}"
    listeners="$(ss -H -ltn "sport = :${port}" || true)"
    [[ -n "${listeners}" ]] || die "no local listener found on port ${port}"
    unexpected="$(awk -v expected="${bind}" '$4 != expected { print $4 }' <<<"${listeners}")"
    [[ -z "${unexpected}" ]] ||
      die "origin port ${port} does not match configured bind ${bind}: ${unexpected}"
  done
fi

printf 'local verification passed: routes=%s chat_canary=contract-only frontend=%s backend=%s; accessibility and CWV require dedicated gates\n' \
  "${#public_routes[@]}" "${front}" "${back}"
