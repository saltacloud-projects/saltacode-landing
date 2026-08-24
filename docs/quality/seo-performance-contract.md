# SEO and performance contract

Every modernization change must preserve indexability and established public behavior while moving measured performance toward explicit targets. Passing these checks does not guarantee search rankings.

## SEO invariants

- Preserve existing public URLs and canonical intent. Add tested permanent redirects before removing or renaming an indexed URL.
- Serve primary marketing copy, headings, navigation, and contact information as static indexable HTML.
- Keep one descriptive title, one meaningful `h1`, accurate Spanish language metadata, unique descriptions, canonical URL, and complete OpenGraph/Twitter previews.
- Generate and validate `robots.txt`, sitemap, and applicable JSON-LD from the same production URL source.
- Keep status codes, redirect chains, trailing-slash policy, host normalization, and `www` policy explicit.
- Never block production crawling through a preview-only `noindex` rule, robots rule, authentication gate, or framework fallback.
- Validate internal links and preserve non-chat contact paths.

## Core Web Vitals field targets

Evaluate mobile and desktop field data at the 75th percentile when sufficient traffic exists:

| Metric | Target |
|---|---|
| LCP | <= 2.5 seconds |
| INP | <= 200 milliseconds |
| CLS | <= 0.1 |

When field data is unavailable, report that limitation and use repeatable lab measurements as provisional evidence.

## Lighthouse lab targets

Use consistent device, network, location, route, and run count:

| Category | Target |
|---|---|
| Performance | >= 95 |
| Accessibility | >= 95 |
| Best Practices | >= 95 |
| SEO | 100 |

These are engineering quality gates, not ranking guarantees. Scores can vary between runs and do not replace Search Console or field Core Web Vitals.

## Performance budgets

Version 3 of the provisional local budgets is based on the repeatable 2026-08-24 Astro preview baseline plus isolated attribution of the agent-first hero animation and the complete light/dark/system theme system. Build-only limits are enforced by `frontend/scripts/verify-build.mjs`; transfer limits remain browser-lab release gates.

| Resource or scenario | Version 3 limit | Gate |
|---|---:|---|
| Generated home HTML | <= 27 KiB raw | Deterministic build assertion |
| Total emitted CSS | <= 18 KiB raw | Deterministic build assertion |
| Initial executable JavaScript | <= 5 KiB raw | Deterministic build assertion |
| Total executable JavaScript | <= 14 KiB raw | Deterministic build assertion |
| Emitted webfonts | 0 bytes | Deterministic build assertion |
| Social preview image | <= 100 KiB raw | Deterministic build assertion |
| Cold initial-page transfer | <= 125 KiB encoded | Repeatable browser lab |
| Cold full-scroll transfer | <= 175 KiB encoded | Repeatable browser lab |

The browser-lab gates require consistent viewport, network, CPU, cache state, route, and run count. Record the median and raw runs. Lighthouse scores, public-origin compression and cache behavior, and 75th-percentile field data are separate evidence and must still be verified.

The reviewed theme delta is +4,681 bytes of raw home HTML, +2,834 bytes of emitted CSS, and +1,927 bytes of initial and total executable JavaScript versus the circuit-hero baseline. It covers three explicit accessible theme choices, the pre-paint system/saved-preference bootstrap, duplicate-download prevention for theme images, optimized light/dark image source metadata, cross-tab/system synchronization, and the shared page-shell controller. The limits retain 1,747 bytes of HTML, 466 bytes of CSS, 1,167 bytes of initial JavaScript, and 2,082 bytes of total JavaScript headroom over the measured build.

The 2026-08-24 post-theme mobile browser lab used Chrome 150 at 390x844, 150 ms latency, 1.6 Mbps download, 750 Kbps upload, 4x CPU throttling, disabled cache, and three cold runs per explicit theme. Light mode recorded 127,857 bytes in every run, 588/596/604 ms LCP, 33/35/44 ms TBT, and 0 CLS; dark mode recorded 125,289 bytes in every run, 596/600/608 ms LCP, 29/33/39 ms TBT, and 0 CLS. Every run used only the selected image variants, had no horizontal overflow or runtime exceptions, and passed the provisional cold initial-transfer gate. Production compression, field data, and Lighthouse remain separate release evidence.

The initial JavaScript allowance covers the CSP-hashed pre-paint theme bootstrap, shared theme/navigation controller, and fingerprinted hero loader. Motion mini and the circuit controller stay in one separate dynamic chunk requested after browser idle and are not requested when reduced motion is preferred. The 404 route may execute only the same CSP-hashed theme bootstrap and shared controller required to honor the persisted preference; `unsafe-inline` and `unsafe-eval` remain prohibited everywhere.

Budget changes require measured evidence and review. Never raise a limit only to make CI pass; first attribute the regression and either remove it or document the reviewed tradeoff.

## Accessibility contract

- Use semantic landmarks and a logical heading hierarchy.
- Preserve keyboard operation, visible focus, skip navigation, reduced-motion behavior, and sufficient contrast.
- Give informative images meaningful alternatives and decorative images empty alternatives.
- Announce chat state and streamed responses without stealing focus.
- Test automated rules plus keyboard and screen-reader critical paths; automated scores alone are insufficient.

## Release evidence

For each release candidate, record changed URLs, redirects, metadata/schema diff, robots/sitemap result, link validation, Lighthouse runs, accessibility checks, asset-budget result, console/network errors, and rollback point. Verify the deployed response, not only the build output.
