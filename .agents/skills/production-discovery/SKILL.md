---
name: production-discovery
description: "Trigger: discovery, production audit, current state, baseline. Establish repository and live evidence before modernization."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill before architecture selection, migration, deployment planning, or claims about the current Saltacode site. Use it for repository and authorized live-state discovery.

## Hard Rules

- Start read-only; do not authenticate, deploy, mutate DNS, or change providers without explicit approval.
- Separate repository facts, live responses, provider state, field data, and unknowns.
- Treat a healthy build, HTTP 200, screenshot, or local preview as incomplete production evidence.
- Redact secrets and personal data.

## Decision Gates

| Evidence need | Action |
|---|---|
| Repository structure | Use CodeGraph first, then targeted file reads. |
| Live behavior | Inspect public responses and redirects reproducibly. |
| Provider/account state | Stop until access and mutation boundaries are authorized. |
| Prior project decision | Search Engram, then verify drift-prone facts. |

## Execution Steps

1. Record scope, environment, date, URLs, and forbidden mutations.
2. Map entry points, build/deploy files, dependencies, content, contacts, and analytics.
3. Capture status codes, redirect chains, headers, robots, sitemap, metadata, schema, and mobile behavior when live checks are authorized.
4. Measure repeatable lab performance and locate field evidence; label missing data.
5. Produce a baseline, risks, unknowns, and the next evidence gate.

## Output Contract

Return verified facts with paths or commands, production unknowns, SEO/performance impact, and prioritized next checks. Never convert an inference into a confirmed fact.

## References

- `../../../docs/discovery/initial-baseline.md`
- `../../../docs/discovery/production-baseline.md`
- `../../../docs/agentic/tooling.md`
