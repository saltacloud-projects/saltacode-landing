#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

require_command curl

base="${SALTACODE_PUBLIC_BASE_URL:-https://saltacode.com.ar}"
[[ "${base}" == "https://saltacode.com.ar" ]] ||
  die "set SALTACODE_PUBLIC_BASE_URL explicitly; only the canonical apex is accepted by this gate"

temporary="$(mktemp -d)"
trap 'rm -rf "${temporary}"' EXIT
user_agent="Saltacode-Release-Verification/1.0 (+https://saltacode.com.ar/)"
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

for index in "${!public_routes[@]}"; do
  route="${public_routes[${index}]}"
  body="${temporary}/route-${index}.html"
  headers="${temporary}/route-${index}.headers"
  curl --fail --silent --show-error --max-time 20 \
    --user-agent "${user_agent}" \
    --dump-header "${headers}" "${base}${route}" >"${body}"
  [[ "$(header_value "${headers}" Content-Type)" == text/html* ]] ||
    die "public ${route} was not served as HTML"
  grep -Fqi "<link rel=\"canonical\" href=\"${base}${route}\"" "${body}" ||
    die "public ${route} has an incorrect canonical URL"
  [[ "$(grep -Eio '<h1([[:space:]][^>]*)?>' "${body}" | wc -l)" == "1" ]] ||
    die "public ${route} must contain exactly one h1"
  ! grep -Eqi "<meta[^>]+name=[\"']robots[\"'][^>]+noindex" "${body}" ||
    die "public ${route} unexpectedly declares noindex"
  verify_security_headers "${headers}" "$([[ "${route}" == "/" ]] && printf yes || printf no)"
done

curl --fail --silent --show-error --max-time 20 --user-agent "${user_agent}" \
  "${base}/robots.txt" >"${temporary}/robots.txt"
curl --fail --silent --show-error --max-time 20 --user-agent "${user_agent}" \
  "${base}/sitemap.xml" >"${temporary}/sitemap.xml"
grep -Fq 'Sitemap: https://saltacode.com.ar/sitemap.xml' "${temporary}/robots.txt" ||
  die "public robots.txt does not advertise the canonical sitemap"
for route in "${public_routes[@]}"; do
  grep -Fq "<loc>${base}${route}</loc>" "${temporary}/sitemap.xml" ||
    die "public sitemap is missing ${route}"
done
grep -Eqi 'mailto:' "${temporary}/route-7.html" || die "public contact page lost its email path"
grep -Eqi 'https://wa\.me/' "${temporary}/route-7.html" ||
  die "public contact page lost its WhatsApp path"

missing_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 20 \
  --user-agent "${user_agent}" \
  "${base}/__saltacode_missing_${RANDOM}")"
[[ "${missing_status}" == "404" ]] || die "public origin must return a real 404, got ${missing_status}"

redirect_path='/contacto/?release_probe=path%2Bquery&empty='
www_result="$(curl --silent --show-error --output /dev/null --max-redirs 0 --max-time 20 \
  --user-agent "${user_agent}" \
  --write-out '%{http_code} %{redirect_url}' "https://www.saltacode.com.ar${redirect_path}" || true)"
www_status="${www_result%% *}"
www_location="${www_result#* }"
[[ "${www_status}" =~ ^30[1278]$ && "${www_location}" == "${base}${redirect_path}" ]] ||
  die "www must redirect directly to the canonical host while preserving path and query; got ${www_result}"

http_result="$(curl --silent --show-error --output /dev/null --max-redirs 0 --max-time 20 \
  --user-agent "${user_agent}" \
  --write-out '%{http_code} %{redirect_url}' "http://saltacode.com.ar${redirect_path}" || true)"
http_status="${http_result%% *}"
http_location="${http_result#* }"
[[ "${http_status}" =~ ^30[1278]$ && "${http_location}" == "${base}${redirect_path}" ]] ||
  die "HTTP must redirect directly to HTTPS while preserving path and query; got ${http_result}"

verify_chat_contract_canary "${base}" "${base}" "${temporary}/chat-canary" "${user_agent}"

printf 'public read-only verification passed: routes=%s chat_canary=contract-only base=%s; this does not prove accessibility, Search Console, rankings, or field CWV\n' \
  "${#public_routes[@]}" "${base}"
