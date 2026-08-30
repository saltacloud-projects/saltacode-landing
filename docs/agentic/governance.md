# Agentic governance

## Decision

The repository uses a small, portable control plane: Git-tracked instructions, skills, validation, and architecture decisions define how work is performed. CodeGraph supplies repository evidence, Engram supplies continuity, and provider-specific tools supply remote evidence. External and machine-global mutations are denied by default.

This is a safety boundary, not an approval ceremony. Routine work should remain a small sequence: classify, inspect, change, validate, record.

## Operating sequence

1. **Classify the action:** read-only, repository-local mutation, external mutation, or machine-global mutation.
2. **Confirm scope:** identify the requested outcome, owned files or service, and rollback boundary.
3. **Collect evidence:** use CodeGraph for structure, then Engram for prior context, then current repository or provider evidence.
4. **Act minimally:** make the smallest reversible change within the owned scope.
5. **Validate and record:** run focused checks, report unknowns, save durable findings to Engram, and add an ADR only when the decision meets the trigger below.

## Mutation policy

| Action | Default | Required condition |
|---|---|---|
| Read repository files, CodeGraph, or local test output | Allowed | Stay inside the task and protect secrets. |
| Edit repository files | Allowed only in the assigned scope | Preserve unrelated changes and run focused validation. |
| Create a local commit | Conditional | The task or repository workflow must authorize it; inspect the staged diff first. |
| Read GitHub or Cloudflare state | Conditional read-only | The task requires provider evidence and an existing authenticated context can be used without changing it. |
| Push, open or edit remote artifacts, release, deploy, change DNS/Tunnel/account settings, or delete remote data | **Denied** | Obtain explicit approval for the exact provider, target, and operation immediately before execution. |
| Install or upgrade global tools, edit user-level configuration, start system services, or repair shared/cloud state | **Denied** | Obtain explicit approval and define impact and rollback first. |
| Store or expose credentials | **Denied** | Use operator-owned secret mechanisms; redact evidence and never persist secrets in Git or Engram. |

Approval for one mutation does not authorize adjacent operations. A configured account, authenticated CLI, broad token, or previous approval is capability, not consent.

## Evidence and tool boundaries

- **CodeGraph is first for structure.** Use it before broad searches for architecture, dependencies, call flow, and impact. Fall back narrowly only after initialization or query failure, and record the fallback.
- **Engram is continuity, not authority.** Search before repeating prior work and save durable discoveries. Current code, runtime, and provider responses override stale memory.
- **Local Engram is useful without cloud replication.** The Git-tracked operating contract and ADRs must remain sufficient on another workstation. Never assume cloud replication succeeded; verify it separately when synchronization matters.
- **`gh` is the GitHub boundary.** Prefer it over guessed remote state or manual UI interpretation, but keep queries read-only until a remote mutation is explicitly approved.
- **Cloudflare tools are the Cloudflare boundary.** Local template validation is not provider verification. Start with read-only account evidence and keep Tunnel, DNS, routes, Access, and deployment changes behind explicit approval.
- **Git is the durable implementation record.** Engram can explain why and accelerate recovery; it does not replace versioned code, reviewable docs, or validation evidence.

## Portable source of truth

The repository must be usable when Engram, CodeGraph, GitHub, or Cloudflare access is unavailable:

- `AGENTS.md` and project skills define the operating contract.
- `docs/decisions/` records durable cross-cutting choices.
- Architecture and quality docs describe current intended boundaries and evidence gates.
- Scripts and tests verify behavior where automation is practical.

Tool-specific caches, local authentication, and synced memories are conveniences. Do not make required project knowledge exist only in them.

## When an ADR is warranted

Create or supersede an ADR only when a decision is durable, cross-cutting, expensive to reverse, security/privacy relevant, or repeatedly disputed. Do not create one for routine refactors, temporary experiments, task logs, or choices already obvious from a narrow implementation.

See the [decision log](../decisions/README.md) for the lightweight lifecycle.
