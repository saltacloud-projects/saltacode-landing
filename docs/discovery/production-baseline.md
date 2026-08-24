# Production baseline — 2026-08-23

This document records read-only evidence captured from the public Saltacode site on **2026-08-23 (America/Argentina/Salta)**. It complements the repository-only baseline in `initial-baseline.md` and does not imply authenticated access to Cloudflare, Netlify, GitHub, Search Console, or analytics.

## Public routing and hosting evidence

| Check | Observed result |
|---|---|
| Primary URL | `https://saltacode.com.ar/` returned HTTP 200. |
| HTTP scheme | Requests over HTTP redirected to HTTPS. |
| Host normalization | `www` returned HTTP 301 to the non-`www` host. |
| Response infrastructure | Headers showed Cloudflare in front of Netlify. |
| Transport policy | The HTTPS response included HSTS. |

These observations identify the public response path, not account ownership, deployment configuration, DNS source of truth, cache rules, or rollback controls.

## Crawl controls and canonical consistency

- A fresh direct request to `https://saltacode.com.ar/robots.txt` returned HTTP 200.
- The response was Cloudflare-managed, included `search=yes` and `Allow: /`, and blocked several named AI crawlers.
- `https://saltacode.com.ar/sitemap.xml` returned HTTP 404.
- The checked-in source canonical and `og:url` use `https://www.saltacode.com.ar/`, but the public `www` host permanently redirects to `https://saltacode.com.ar/`.

The canonical/OpenGraph host therefore conflicts with the observed redirect target. Resolve the production host policy before generating canonical URLs, structured data, sitemap entries, or social preview URLs.

## Public discoverability

The Saltacode site and its LinkedIn company presence were publicly discoverable during this audit. That confirms public visibility only. Exact Google index coverage, Google-selected canonical, search queries, impressions, crawl errors, backlinks, manual actions, and property ownership remain unknown without authorized Search Console evidence.

## Synthetic cold-mobile measurement

One synthetic lab run used a **390 × 844** viewport, **4× CPU slowdown**, **150 ms RTT**, and **1.638 Mbps throughput** with a cold load.

| Measurement | Result |
|---|---:|
| FCP | 1.84 s |
| LCP | 28.16 s |
| CLS | 0.245 |
| TBT | 35 ms |
| Load event | 28.11 s |
| Requests | 62 |
| Transfer | 5.56 MB |
| Image transfer | 5.12 MB |
| LCP resource | `screens01.png`, approximately 1.99 MB |

The run exposes a severe cold-load LCP and an elevated CLS under the stated constraints. Images accounted for most transferred bytes, and the largest hero screen was the observed LCP resource.

## Lab versus field evidence

This is a **synthetic lab measurement**, not real-user Core Web Vitals. It is useful for reproducing and diagnosing a constrained cold load, but it does not establish the 75th-percentile LCP, INP, or CLS experienced by users. Those field metrics remain unknown until CrUX or equivalent authorized real-user data is available.

A PageSpeed Insights API request returned HTTP 429, so no PSI result was recorded. Do not substitute the synthetic run for missing PSI, CrUX, or Search Console evidence.

## Immediate discovery implications

1. Align the canonical, OpenGraph URL, redirects, sitemap host, and future structured data on one production host policy.
2. Provide a valid production sitemap and verify that Cloudflare-managed robots behavior matches the intended crawler policy.
3. Optimize the hero/LCP path and below-fold image delivery before enforcing final budgets.
4. Capture repeatable multi-run lab evidence and authorized field/Search Console evidence before and after migration.
5. Discover Cloudflare and Netlify ownership, build, redirect, header, cache, and rollback configuration read-only before changing deployment architecture.
