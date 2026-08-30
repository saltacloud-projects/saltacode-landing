---
name: seo-regression
description: "Trigger: SEO, migration, canonical, redirects, metadata, sitemap, robots. Prevent discoverability regressions with evidence gates."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill for changes to routes, page structure, rendering, content, metadata, schema, redirects, hosting, or crawl controls.

## Hard Rules

- Preserve established public URLs and canonical intent or add tested permanent redirects.
- Keep primary copy, headings, navigation, and contacts in static indexable HTML.
- Do not promise ranking outcomes or treat a Lighthouse SEO score as a ranking guarantee.
- Never ship preview `noindex`, robots blocks, authentication, or fallback status codes to production.

## Decision Gates

| Change | Required gate |
|---|---|
| URL or host changes | Redirect map, chain check, canonical and sitemap update. |
| Content/rendering changes | Rendered HTML, heading, link, and mobile checks. |
| Metadata/schema changes | Validator output and preview-card inspection. |
| No field/Search Console access | Report the limitation; do not infer indexing success. |

## Execution Steps

1. Diff URLs, status codes, canonicals, titles, descriptions, language, headings, and indexable copy.
2. Validate robots, sitemap, JSON-LD, OpenGraph, Twitter metadata, and internal links.
3. Check host, trailing-slash, and redirect normalization.
4. Compare preview output against the verified baseline.
5. Record evidence, unresolved live checks, and rollback conditions.

## Output Contract

Return a pass/fail matrix, exact affected URLs and files, evidence for every failure, remaining unknowns, and remediation priority.

## References

- `../../../docs/quality/seo-performance-contract.md`
- `../../../docs/discovery/initial-baseline.md`
