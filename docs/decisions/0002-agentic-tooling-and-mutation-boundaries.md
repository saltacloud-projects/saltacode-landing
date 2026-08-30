# 0002: Keep agentic tooling portable and mutations explicit

- **Status:** Accepted
- **Date:** 2026-08-30
- **Owners:** Repository maintainers
- **Supersedes:** None
- **Superseded by:** None

## Decision

Keep the agentic operating contract and durable decisions in the repository. Use CodeGraph first for structural evidence, Engram for continuity, `gh` for GitHub evidence, and Cloudflare tools for Cloudflare evidence. Treat every external or machine-global mutation as denied by default until the exact target and operation receive explicit approval.

## Context

Tool availability varies by workstation and authentication can outlive the task that created it. Engram local memory is operational and useful, but cloud replication is not a guaranteed project property. Provider CLIs can expose powerful write operations even when the task only needs read-only evidence. Without a portable source of truth and a clear mutation boundary, convenience becomes accidental authority.

Detailed operating rules are maintained in [Agentic governance](../agentic/governance.md), while dated tool availability is recorded in [Agentic tooling](../agentic/tooling.md).

## Consequences

- Another workstation can recover the operating decisions from Git without depending on local memory, authentication, or caches.
- CodeGraph and Engram reduce repeated exploration, but current repository, runtime, and provider evidence remain authoritative.
- Local Engram can be used even when cloud sync is unavailable; synchronization and repair are separate operations and are never assumed.
- GitHub pushes and remote artifacts, Cloudflare changes, deployments, destructive provider actions, global installations, and shared-state repairs require explicit approval.
- Missing preferred tooling may slow discovery, but it does not justify an unapproved install or provider mutation; use and record a bounded fallback.

## Review trigger

Review this decision if the repository adopts an approved centralized control plane that provides portable, audited authorization and synchronization without weakening the local-first or default-deny boundaries.
