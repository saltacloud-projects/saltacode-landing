---
name: agent-platform-quality
description: "Trigger: agent platform, multi-agent, multi-source, persistence, migrations, panel, RBAC. Protect agent-platform boundaries and quality."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill for changes to agent runtime, persisted configuration, resource bindings, channel routes, credentials, conversations, audit, migrations, or the administration panel.

## Hard Rules

- Apply `pragmatic-clean-architecture`: preserve current behavior and introduce only the smallest evidenced boundary.
- Keep provider, channel, source, tool, knowledge, and document-area libraries platform-wide; make agent use explicit through bindings, runtime configuration, access policy, and routes.
- Scope every runtime operation by resolved agent and route. Never infer ownership from a default agent, phone number, or legacy row.
- Keep agent-specific workflows, business names, prompts, source semantics, and tenant rules out of shared runtime code. Model them as persisted configuration, knowledge, or a named integration adapter.
- Keep credentials write-only, encrypted at rest, redacted from logs and responses, and unavailable to browser code.
- Pair persistence changes with explicit forward and rollback migrations. Preserve unknown legacy ownership as null; never invent a backfill.
- Enforce RBAC and agent isolation server-side. Panel selection is context, not authorization.
- Attribute new audit records to the resolved agent and channel route; do not relabel legacy history.

## Decision Gates

| Change crosses | Required evidence |
|---|---|
| Pure policy or refactor | Focused unit tests; add no new layer without a proven seam. |
| Database model or persistence | Migration upgrade and drift check, unit coverage, and PostgreSQL integration tests. |
| Panel or RBAC | API authorization/isolation tests plus panel check, build, and E2E. |
| Channel, route, or BFF contract | Agent API integration tests and BFF contract tests when the public boundary changes. |
| Credential flow | Encryption, write-only response, redaction, and failure-path tests. |

## Execution Steps

1. Map callers and ownership with CodeGraph; classify each resource as platform library or agent-owned binding/runtime data.
2. State the agent, route, persistence, RBAC, legacy-data, and secret invariants that must remain true.
3. Implement one bounded vertical slice; reject pass-through layers and speculative repositories.
4. Add migrations and compatibility handling before changing readers or panel flows.
5. Run `pnpm verify:agent-api`, `pnpm verify:agent-panel`, and `pnpm verify:backend` only when their boundary is crossed.
6. Finish with `delivery-checkpoint`; report exclusions rather than absorbing concurrent work.

## Output Contract

Return the ownership boundary, invariants preserved, changed files, migrations and rollback impact, exact validation evidence, legacy-data disposition, security risks, and remaining unknowns.

## References

- `../../../agent-platform/docs/architecture/administration-model.md`
- `../../../agent-platform/docs/architecture/platform.md`
- `../../../docs/architecture/platform-topology.md`
- `../../../scripts/quality/verify.sh`
- `../pragmatic-clean-architecture/SKILL.md`
- `../delivery-checkpoint/SKILL.md`
