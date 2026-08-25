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

The reviewed theme delta is +4,681 bytes of raw home HTML, +2,834 bytes of emitted CSS, and +1,927 bytes of initial and total executable JavaScript versus the circuit-hero baseline. It covers three explicit accessible theme choices, the pre-paint system/saved-preference bootstrap, duplicate-download prevention for theme images, optimized light/dark image source metadata, cross-tab/system synchronization, and the shared page-shell controller.

The 2026-08-24 post-theme mobile browser lab used Chrome 150 at 390x844, 150 ms latency, 1.6 Mbps download, 750 Kbps upload, 4x CPU throttling, disabled cache, and three cold runs per explicit theme. Light mode recorded 127,857 bytes in every run, 588/596/604 ms LCP, 33/35/44 ms TBT, and 0 CLS; dark mode recorded 125,289 bytes in every run, 596/600/608 ms LCP, 29/33/39 ms TBT, and 0 CLS. Every run used only the selected image variants, had no horizontal overflow or runtime exceptions, and passed the provisional cold initial-transfer gate. Production compression, field data, and Lighthouse remain separate release evidence.

The historical-lockup correction replaces the simplified inline approximation with the production paths, gradients, vector wordmark, tagline, drawing sequence, easing, and delays. It adds no font request, renders at 220 CSS pixels instead of 300, emits only the selected theme variant, and swaps to a static exact vector before paint when reduced motion is preferred. That checkpoint build was 27,302 bytes of HTML, 18,306 bytes of CSS, 4,325 bytes of initial JavaScript, and 12,625 bytes of total JavaScript, leaving 346, 126, 795, and 1,711 bytes of headroom respectively without raising a limit.

The exact animated vectors are 26,527 raw bytes per theme. Before origin compression, the equivalent mobile lab transferred 140,989 bytes in light mode and 138,625 bytes in dark mode, exceeding the 128,000-byte cold-transfer gate even though CLS remained 0. The limit was not raised: the Node static server now negotiates gzip for compressible responses and emits `Vary: Accept-Encoding`; the selected animated SVG transfers 4,841 bytes locally.

The final post-compression mobile lab used the same conditions and three cold runs per explicit theme. Light mode recorded 81,089 bytes in every run, 480/492/500 ms LCP, 31/35/58 ms TBT, and 0 CLS; dark mode recorded 78,725 bytes in every run, 488/500/504 ms LCP, 21/28/37 ms TBT, and 0 CLS. No run fetched the wrong theme variant, overflowed horizontally, or raised a runtime exception. This is local lab evidence only; public Cloudflare compression, field data, and Lighthouse remain release-stage checks.

The responsive-navbar and client-carousel change uses the official themed brand lockup, moves the single static client section into the hero, removes the four duplicated service-summary cards, and progressively creates the second carousel group only in browsers that allow motion. The carousel uses compositor-friendly CSS transforms rather than a new dependency or hydrated island, pauses on hover or keyboard focus, fades at both edges, and stays static when reduced motion is preferred. After removing the redundant client eyebrow and visible motion control, the current build is 26,583 bytes of HTML, 18,400 bytes of CSS, 4,810 bytes of initial JavaScript, and 13,110 bytes of total JavaScript, leaving 1,065, 32, 310, and 1,226 bytes of headroom respectively without raising a limit.

The last complete Chrome 150 mobile lab before that markup-only cleanup used 390x844, 150 ms latency, 1.6 Mbps download, 750 Kbps upload, 4x CPU throttling, disabled cache, and three cold runs per explicit theme. Light mode transferred 67,656 bytes in every run with 480/484/564 ms LCP, 21/28/48 ms TBT, and 0 CLS; dark mode transferred 66,642 bytes in every run with 476/488/564 ms LCP, 20/24/47 ms TBT, and 0 CLS. Functional checks at 320px, 390px, and 1440px found no horizontal document overflow, wrong theme variant, duplicate accessible client group, or runtime exception. The cleanup was verified against the rebuilt served HTML and static budgets, but the full throttled lab was not rerun. These remain local lab results, not public field evidence.

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
