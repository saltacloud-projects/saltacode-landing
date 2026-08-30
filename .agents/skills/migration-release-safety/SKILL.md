---
name: migration-release-safety
description: "Trigger: database migration, schema release, Alembic, rollback. Protect persistent data across forward releases and compatibility gates."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill for persistent-schema changes, data backfills, migration preflight, release receipts, backup requirements, or application rollback across database revisions.

## Hard Rules

- Map the current revision, target revision, writers, readers, and stored data before editing.
- Prefer forward, additive, backward-compatible migrations; make backfills bounded, restartable, and observable.
- Never drop, narrow, rename in place, or restore a database without explicit authorization and verified backup/restore evidence.
- Keep migration execution controlled and one-shot; never hide it in ordinary application startup.
- Record immutable artifacts, schema before/after, compatibility, and verification without secrets, secret values, or secret-derived hashes.
- Preserve databases, documents, conversations, histories, and audit records during application rollback.
- This skill prepares and verifies a release plan; it never authorizes deploy, rollback, backup, restore, DNS, or provider mutation.

## Decision Gates

| Evidence | Action |
|---|---|
| Additive and backward-compatible | Expand, migrate, verify, then contract in a later release. |
| Large data backfill | Chunk, checkpoint, make retries idempotent, and measure completion. |
| Destructive or incompatible change | Require a multi-release expand/contract plan plus tested backup restoration. |
| Target app matches current schema and receipt | Permit application rollback after preflight and explicit authorization. |
| Schema advanced or compatibility is unproven | Block rollback; ship a forward fix or review a separate compatibility operation. |

## Execution Steps

1. Inspect migration heads, models, persistent volumes, and every affected runtime consumer.
2. Define forward migration, compatibility window, failure boundary, backup requirement, and receipt fields.
3. Test empty-database upgrade, upgrade from the supported prior revision, schema drift, retry behavior, and representative data preservation.
4. Run read-only preflight; require explicit authorization immediately before any external or production mutation.
5. Verify internal health, panel access, revision, document/history preservation, and receipt integrity; block unsafe rollback.

## Output Contract

Return revisions, compatibility evidence, backup/restore status, commands prepared or executed, health and data checks, secret-free receipt location, rollback eligibility, blockers, and explicit confirmation that no release was authorized by this skill.

## References

- `../../../agent-platform/docs/operations/release-and-rollback.md`
- `../../../agent-platform/fastapi/alembic-platform.ini`
- `../../../infrastructure/ROLLBACK.md`
- `../../../scripts/quality/verify.sh`
- `../delivery-checkpoint/SKILL.md`
