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

Capture preview and production baselines before enforcing numeric resource budgets. Then version budgets for HTML, critical CSS, initial JavaScript, fonts, LCP media, total initial transfer, third-party requests, and main-thread work. A budget change requires evidence and review; do not silently raise it to make CI pass.

## Accessibility contract

- Use semantic landmarks and a logical heading hierarchy.
- Preserve keyboard operation, visible focus, skip navigation, reduced-motion behavior, and sufficient contrast.
- Give informative images meaningful alternatives and decorative images empty alternatives.
- Announce chat state and streamed responses without stealing focus.
- Test automated rules plus keyboard and screen-reader critical paths; automated scores alone are insufficient.

## Release evidence

For each release candidate, record changed URLs, redirects, metadata/schema diff, robots/sitemap result, link validation, Lighthouse runs, accessibility checks, asset-budget result, console/network errors, and rollback point. Verify the deployed response, not only the build output.
