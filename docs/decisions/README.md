# Architecture decision log

## Decision

Use short ADRs only for durable choices that future contributors could reasonably revisit. The decision appears first, evidence is concise, and supersession is explicit. This log is not a meeting record or a second issue tracker.

## Create an ADR when

- the choice changes a cross-cutting architecture or trust boundary;
- it affects SEO, performance, security, privacy, persistence, deployment, or agentic governance;
- reversing it later would be costly or risky; or
- the same decision keeps being reopened because its rationale is not portable.

Do not create an ADR for a routine refactor, a temporary experiment, a task checklist, or a local implementation detail with an obvious rollback.

## Lifecycle

| Status | Meaning |
|---|---|
| `Proposed` | The decision is reviewable but not yet the operating default. |
| `Accepted` | The decision is the current operating default. |
| `Superseded` | A newer ADR replaces it; both documents link to each other. |
| `Rejected` | The proposal was considered and intentionally not adopted. |

To record a decision:

1. Copy [`0000-template.md`](0000-template.md) to the next `NNNN-kebab-case.md` number.
2. Fill in status, date, decision, context, consequences, and review trigger.
3. Link concrete evidence rather than duplicating large design documents.
4. If it replaces a decision, set `Supersedes` in the new ADR and set the old ADR to `Superseded by [NNNN]`.
5. Add it to the index below.

An accepted ADR changes through a new ADR, not by silently rewriting its original rationale. Small factual corrections that do not alter the decision are allowed.

## Index

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-incremental-architecture.md) | Accepted | Evolve architecture incrementally from evidenced needs. |
| [0002](0002-agentic-tooling-and-mutation-boundaries.md) | Accepted | Keep agentic governance portable and deny external/global mutations by default. |
