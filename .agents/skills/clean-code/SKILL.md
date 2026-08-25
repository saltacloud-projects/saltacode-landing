---
name: clean-code
description: "Trigger: clean code, refactor, code smell, technical debt, deuda técnica. Simplify code without changing verified behavior."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill for maintainability audits, code-smell remediation, duplication removal, naming improvements, or behavior-preserving refactors.

## Hard Rules

- Establish current behavior and focused tests before editing.
- Preserve public contracts, SEO, accessibility, security, and performance unless the task explicitly changes them.
- Cite each smell with a file, symbol, and concrete maintenance cost; do not invent speculative debt.
- Prefer deletion, direct naming, cohesive functions, and explicit dependencies over new abstractions.
- Extract only stable repeated behavior; do not abstract coincidental similarity or create generic base layers for one use.
- Keep mechanical cleanup separate from behavior or architecture changes.

## Decision Gates

| Evidence | Action |
|---|---|
| Dead or unreachable code | Prove no callers with CodeGraph and tests, then remove it. |
| Repeated domain rule | Extract one named implementation at the owning boundary. |
| Long unit with multiple reasons to change | Split by responsibility and test each seam. |
| Complex conditional | Name the policy first; add polymorphism only when variants genuinely evolve. |
| Explanatory comment | Improve the code; retain comments that explain constraints or rationale. |

## Execution Steps

1. Map the affected symbols and callers with CodeGraph.
2. Record observable behavior and the smallest relevant test gate.
3. Rank smells by user risk, change frequency, and maintenance cost.
4. Refactor one bounded smell without altering contracts.
5. Run focused and repository gates; inspect the final diff for accidental scope.

## Output Contract

Return evidence-backed smells, fixes made, behavior preserved, tests run, remaining debt, and rollback boundary.

## References

- `../../../AGENTS.md`
- `../../../docs/quality/seo-performance-contract.md`
- `../delivery-checkpoint/SKILL.md`
