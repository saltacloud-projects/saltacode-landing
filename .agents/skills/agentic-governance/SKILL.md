---
name: agentic-governance
description: "Trigger: agentic governance, AGENTS, agents, skills, CodeGraph, MCP, Engram, validator or CI drift. Keep repository automation coherent and current."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill when auditing or changing `AGENTS.md`, project agents, skills, CodeGraph, MCP/tool declarations, Engram practices, validators, agentic CI, or their freshness.

## Hard Rules

- Use CodeGraph for structure and Engram for prior decisions before repeating discovery; verify stale or drift-prone facts against current repository, runtime, or provider evidence.
- Keep portable policy and durable decisions in versioned repository contracts. Never make local memory, authentication, caches, or generated registries the only source of truth.
- Default-deny global installs/configuration and remote GitHub, Cloudflare, CI, deployment, or provider mutations until the exact target, operation, rollback, and explicit authorization are established.
- Preserve one canonical declaration for each agent, skill, tool, and rule. Derive indexes and checks where practical; do not add duplicated hardcoded inventories.
- Update registries, validators, CI, and documentation only when evidence proves drift. A touched skill alone does not justify unrelated churn.
- Never store secrets in Git, logs, prompts, or Engram. Preserve unrelated concurrent work and assigned file ownership.
- Close every bounded change through `delivery-checkpoint`; never imply commit, push, deploy, or provider verification without evidence.

## Decision Gates

| Evidence | Action |
|---|---|
| Repository declaration conflicts with runtime | Identify authority and reconcile the smallest owned artifact. |
| Inventory is duplicated | Derive it from the canonical directory or manifest; document only unavoidable duplication. |
| Tool/version may be stale | Verify read-only; record date, source, and remaining unknowns before proposing change. |
| Global or remote mutation is required | Stop unless explicitly authorized with bounded rollback. |
| No drift exists | Report no change; do not rewrite registry, validator, CI, or docs. |

## Execution Steps

1. Resolve the repository root; inspect CodeGraph status and relevant Engram context.
2. Map versioned declarations, derived artifacts, validators, CI consumers, and current runtime evidence.
3. Record each drift item with its canonical source, evidence, impact, and owner.
4. Make the smallest repository-local correction; align only derived artifacts proven stale.
5. Run focused schema/reference checks and the agentic validator or closest CI-equivalent command.
6. Inspect the owned diff, save durable findings to Engram, and execute `delivery-checkpoint` within the authorized mutation boundary.

## Output Contract

Return repository truth, runtime evidence, drift found or disproved, files changed, validation results, freshness unknowns, withheld mutations, rollback boundary, and the next review trigger.

## References

- `../../../AGENTS.md`
- `../../../docs/agentic/governance.md`
- `../../../docs/agentic/tooling.md`
- `../../../docs/decisions/0002-agentic-tooling-and-mutation-boundaries.md`
- `../../../docs/skill-style-guide.md`
- `../../../.codex/config.toml`
- `../../../scripts/agentic/validate-layer.sh`
- `../../../.github/workflows/agentic-layer.yml`
- `../delivery-checkpoint/SKILL.md`
