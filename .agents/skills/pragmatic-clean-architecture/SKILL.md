---
name: pragmatic-clean-architecture
description: "Trigger: pragmatic clean architecture, incremental boundaries, overengineering. Apply the smallest justified Clean Code and architecture change."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill when a change needs both code-level cleanup and a decision about boundaries, layers, ports, or adapters.

## Hard Rules

- Establish current behavior, callers, and focused tests before editing.
- Improve naming, cohesion, duplication, and explicit dependencies before adding architecture.
- Introduce a boundary only for evidenced volatility, policy complexity, ownership, or a valuable test seam.
- Never create generic repositories, marker interfaces, pass-through services, empty layers, or folders without an owning responsibility.
- Preserve public contracts and migrate one bounded vertical slice at a time.
- Record what applies now and the concrete trigger that would justify the next layer.

## Decision Gates

| Evidence | Action now |
|---|---|
| Local smell with stable dependencies | Refactor directly; add no layer. |
| Repeated stable policy or invariant | Extract one named cohesive unit. |
| Volatile external dependency or costly test seam | Add a consumer-owned port and one adapter. |
| Cross-process payload | Define and validate a versioned contract. |
| Speculative future need only | Defer and record its activation trigger. |

## Execution Steps

1. Map callers and dependencies with CodeGraph.
2. State the maintenance cost, change pressure, and behavior to preserve.
3. Apply the smallest Clean Code improvement first.
4. If a decision gate passes, introduce only the boundary required by that evidence and keep dependencies inward.
5. Run focused and crossing contract tests; inspect the diff for ceremonial abstractions.
6. Record the current disposition and the observable trigger for another layer.

## Output Contract

Return evidence, cleanup applied now, boundaries added or deferred, next-layer triggers, contracts and tests preserved, remaining risks, and rollback boundary.

## References

- `../../../docs/skill-style-guide.md`
- `../clean-code/SKILL.md`
- `../clean-architecture/SKILL.md`
- `../delivery-checkpoint/SKILL.md`
