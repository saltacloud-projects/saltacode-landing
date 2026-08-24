---
name: cloudflare-release
description: "Trigger: Cloudflare Pages, Wrangler, preview deploy, production release, rollback. Verify and promote releases with explicit authorization."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill for Cloudflare discovery, Pages configuration, preview deployment, DNS, redirects, headers, secrets, production promotion, or rollback.

## Hard Rules

- Begin read-only. Never authenticate, install Wrangler, deploy, mutate DNS, secrets, routes, or account state without explicit approval.
- Do not infer production state from repository configuration or a successful build.
- Use previews before production and verify the deployed response.
- Keep secrets in provider-managed bindings; never commit them.

## Decision Gates

| State | Action |
|---|---|
| Account/project unknown | Inventory read-only after authorization. |
| Wrangler absent | Add a pinned project dependency only in an approved migration phase. |
| Preview fails quality gates | Stop; do not promote. |
| Production regression | Execute the pre-recorded rollback path, then verify externally. |

## Execution Steps

1. Record account, zone, Pages project, branch mapping, build command, output path, domains, and mutation scope.
2. Capture current DNS, redirects, headers, cache rules, secrets names, and rollback point without exposing values.
3. Build deterministically and validate the artifact.
4. Deploy a preview only when authorized; run SEO, accessibility, performance, link, and response checks.
5. Promote only with explicit approval, then verify production and document rollback evidence.

## Output Contract

Return authorization scope, commands, provider responses, preview/production evidence, quality-gate results, unknowns, and rollback reference.

## References

- `../../../docs/agentic/tooling.md`
- `../../../docs/architecture/technology-direction.md`
- `../../../docs/quality/seo-performance-contract.md`
