---
name: cloudflare-release
description: "Trigger: Cloudflare Tunnel, host release, production deploy, rollback. Verify self-hosted releases with explicit authorization."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill for host-managed Cloudflare Tunnel discovery, self-hosted site releases, DNS, ordered ingress routes, deployed-response verification, or rollback.

## Hard Rules

- Begin read-only. Never authenticate, deploy, start or install services, mutate DNS, Tunnel routes, secrets, or account state without explicit approval.
- Do not infer production state from repository configuration or a successful build.
- Keep `cloudflared` host-managed and both browser-facing origins bound to loopback; do not add Cloudflare Pages, Nginx, or Caddy without a measured requirement.
- Treat the site and agent platform as independent release units. A site release must not rebuild, migrate, or roll back the agent platform.
- Keep secret values in protected files outside Git and report only secret names or paths.

## Decision Gates

| State | Action |
|---|---|
| Live DNS, Tunnel, or host state unknown | Keep it explicitly unknown; inventory read-only only when access is authorized. |
| Local or sandbox gate fails | Stop; do not promote. |
| Agent platform change is mixed into a site release | Split the release units before continuing. |
| Production regression | Use the recorded site release receipt and bounded rollback, then verify externally. |

## Execution Steps

1. Record the authorized mutation scope and capture the current host release receipt, service state, Tunnel route order, DNS, redirects, headers, cache rules, secret paths, and rollback point without exposing values.
2. Run the repository quality gate and the infrastructure preflight against an external environment file with an immutable release tag and digest-pinned Redis image.
3. Build and exercise the site unit locally or in sandbox; verify health, canonical redirects, robots, sitemap, real 404 behavior, contact paths, chat availability, accessibility, and performance budgets.
4. Run `infrastructure/scripts/deploy-site.sh` only after explicit production authorization. It may release only frontend, BFF, and site Redis.
5. Verify the public canonical origin and record provider responses plus the immutable receipt. On regression, execute the bounded receipt-based rollback and verify again.

## Output Contract

Return authorization scope, released unit, commands, provider and host responses, sandbox/production evidence, quality-gate results, unknowns, immutable release receipt, and rollback evidence. State explicitly whether DNS or Tunnel state changed.

## References

- `../../../docs/agentic/tooling.md`
- `../../../docs/architecture/technology-direction.md`
- `../../../docs/architecture/platform-topology.md`
- `../../../docs/quality/seo-performance-contract.md`
- `../../../infrastructure/README.md`
