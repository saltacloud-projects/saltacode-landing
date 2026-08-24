#!/usr/bin/env bash

set -Eeuo pipefail

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

command -v curl >/dev/null 2>&1 || die "required command not found: curl"

base="${SALTACODE_PUBLIC_BASE_URL:-https://saltacode.com.ar}"
[[ "${base}" == "https://saltacode.com.ar" ]] ||
  die "set SALTACODE_PUBLIC_BASE_URL explicitly; only the canonical apex is accepted by this gate"

temporary="$(mktemp -d)"
trap 'rm -rf "${temporary}"' EXIT

curl --fail --silent --show-error --max-time 20 -D "${temporary}/headers" \
  "${base}/" >"${temporary}/index.html"
curl --fail --silent --show-error --max-time 20 "${base}/robots.txt" >"${temporary}/robots.txt"
curl --fail --silent --show-error --max-time 20 "${base}/sitemap.xml" >"${temporary}/sitemap.xml"

grep -Eqi '<link[^>]+rel="canonical"[^>]+href="https://saltacode\.com\.ar/?"' \
  "${temporary}/index.html" || die "public canonical is missing or incorrect"
grep -Fq 'Sitemap: https://saltacode.com.ar/sitemap.xml' "${temporary}/robots.txt" ||
  die "public robots.txt does not advertise the canonical sitemap"
grep -Fq '<loc>https://saltacode.com.ar/' "${temporary}/sitemap.xml" ||
  die "public sitemap does not contain the canonical homepage"

missing_status="$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 20 \
  "${base}/__saltacode_missing_${RANDOM}")"
[[ "${missing_status}" == "404" ]] || die "public origin must return a real 404, got ${missing_status}"

www_result="$(curl --silent --show-error --output /dev/null --max-redirs 0 --max-time 20 \
  --write-out '%{http_code} %{redirect_url}' https://www.saltacode.com.ar/ || true)"
www_status="${www_result%% *}"
www_location="${www_result#* }"
[[ "${www_status}" =~ ^30[1278]$ && "${www_location}" == "https://saltacode.com.ar/" ]] ||
  die "www must redirect directly to https://saltacode.com.ar/; got ${www_result}"

grep -Eqi '^x-content-type-options:[[:space:]]*nosniff' "${temporary}/headers" ||
  die "public response is missing X-Content-Type-Options: nosniff"

printf 'public read-only verification passed for %s; this does not prove Search Console or field CWV state\n' \
  "${base}"
