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

Version 2 of the provisional local budgets is based on the repeatable 2026-08-24 Astro preview baseline plus isolated attribution of the agent-first hero animation. Build-only limits are enforced by `frontend/scripts/verify-build.mjs`; transfer limits remain browser-lab release gates.

| Resource or scenario | Version 2 limit | Gate |
|---|---:|---|
| Generated home HTML | <= 22 KiB raw | Deterministic build assertion |
| Total emitted CSS | <= 15 KiB raw | Deterministic build assertion |
| Initial executable JavaScript | <= 2.5 KiB raw | Deterministic build assertion |
| Total executable JavaScript | <= 12 KiB raw | Deterministic build assertion |
| Emitted webfonts | 0 bytes | Deterministic build assertion |
| Social preview image | <= 100 KiB raw | Deterministic build assertion |
| Cold initial-page transfer | <= 125 KiB encoded | Repeatable browser lab |
| Cold full-scroll transfer | <= 175 KiB encoded | Repeatable browser lab |

The browser-lab gates require consistent viewport, network, CPU, cache state, route, and run count. Record the median and raw runs. Lighthouse scores, public-origin compression and cache behavior, and 75th-percentile field data are separate evidence and must still be verified.

The initial JavaScript allowance covers the CSP-hashed navigation controller and the fingerprinted hero loader. Motion mini and the orbit controller stay in one separate dynamic chunk requested after browser idle and are not requested when reduced motion is preferred. `unsafe-inline`, `unsafe-eval`, and executable scripts on the 404 route remain prohibited.

Budget changes require measured evidence and review. Never raise a limit only to make CI pass; first attribute the regression and either remove it or document the reviewed tradeoff.

## Accessibility contract

- Use semantic landmarks and a logical heading hierarchy.
- Preserve keyboard operation, visible focus, skip navigation, reduced-motion behavior, and sufficient contrast.
- Give informative images meaningful alternatives and decorative images empty alternatives.
- Announce chat state and streamed responses without stealing focus.
- Test automated rules plus keyboard and screen-reader critical paths; automated scores alone are insufficient.

## Release evidence

For each release candidate, record changed URLs, redirects, metadata/schema diff, robots/sitemap result, link validation, Lighthouse runs, accessibility checks, asset-budget result, console/network errors, and rollback point. Verify the deployed response, not only the build output.
