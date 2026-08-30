# Agentic tooling

## Decisions

1. Use **CodeGraph first** for repository structure, call paths, references, and blast radius.
2. Use **Engram second** to recover prior decisions and record durable findings; verify current facts against the repository or provider.
3. Use **`gh` for GitHub** and **Cloudflare tools for Cloudflare** when current provider evidence is required.
4. Treat every external or machine-global mutation as **denied by default**. Authentication or tool availability is never authorization.
5. Keep portable decisions in Git-tracked documentation and ADRs. Engram improves continuity, but it is not the only copy of a decision.

The operating rules and mutation matrix are in [Agentic governance](governance.md). Durable architectural choices are indexed in [Architecture decisions](../decisions/README.md).

## Tool priority

| Order | Tool | Use it for | Boundary |
|---|---|---|---|
| 1 | CodeGraph | Architecture, dependencies, symbol references, callers, and impact. | Check the repository index before broad filesystem searches. Never reuse an index across worktrees. |
| 2 | Engram | Recent context, prior decisions, discoveries, and session summaries. | Memory can be stale or local-only. Confirm drift-prone facts with current evidence. |
| 3 | `gh` | GitHub repositories, issues, pull requests, Actions, releases, and settings. | Prefer read-only queries. Any remote mutation needs explicit approval and a bounded target. |
| 4 | `cloudflared` and approved Cloudflare CLI/API tools | Tunnel configuration, routes, DNS, account state, and provider verification. | Validate locally first. Provider mutations and credential operations need explicit approval. |
| 5 | Narrow shell and repository tools | Known files, focused tests, builds, and local validation. | Use after CodeGraph for structural questions; stay inside the assigned file ownership. |

If a preferred tool is unavailable, use the narrowest read-only fallback and record the limitation. Do not install or globally configure a replacement without approval.

## Verified local status

Checked on 2026-08-30:

| Tool | Status | Safe default |
|---|---|---|
| CodeGraph | `1.5.0`; repository index present and up to date at the check. | Explore structure and impact before broad filesystem searches. Let the watcher sync normally. |
| Engram | Local project context and SQLite/WAL checks are healthy. Cloud replication is currently blocked by invalid pending prompt mutations. | Use local memory, but do not assume cloud replication or attempt repair without a separately approved operation. |
| `gh` | `2.96.0`; a local authenticated context may exist. | Query only when GitHub evidence is in scope. Do not push or mutate repository settings implicitly. |
| `cloudflared` | `2026.7.3`; binary available. | Validate sanitized configuration locally. Do not create, route, delete, or change a Tunnel or DNS record implicitly. |
| Node / pnpm | Node `24.17.0`; pnpm `11.11.0`. | Use the committed pnpm version and frozen lockfile. |
| Python / uv | Python 3.12 project target; uv `0.11.23`. | Use each Python workspace's committed lockfile. |
| Docker / Compose | Docker `29.6.2`; Compose `5.3.1`. | Validate models before starting services; use operator-owned environment and secret files. |
| Wrangler | Not installed. | It is not required by the self-hosted Tunnel topology. Add it only for an approved Workers or Pages requirement. |

Versions, authentication, local health, CI availability, and production availability are separate facts and can drift independently.

## Quick validation path

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm check
pnpm test

(cd backend && uv sync --locked --all-groups && uv run ruff format --check . \
  && uv run ruff check . && uv run pytest \
  && uv run python scripts/export_contracts.py --check)

bash scripts/agentic/validate-layer.sh
```

Compose, Tunnel-template, systemd, local probe, and public probe commands live in [`../../infrastructure/README.md`](../../infrastructure/README.md). They depend on protected operator configuration outside Git; never substitute real secrets into documentation, logs, or committed files.

## Orchestration

1. Define the outcome, scope, write owner, mutation boundary, rollback boundary, and validation.
2. Recover structure with CodeGraph and relevant history with Engram before repeating discovery.
3. Assign one writer to each overlapping file slice; parallelize only independent work.
4. Implement the smallest reversible work unit and validate it locally.
5. Use provider-specific tools only when provider evidence is required and the mutation boundary is authorized.
6. Record durable decisions in ADRs, save non-obvious findings to Engram, and report remaining unknowns.

## Delivery maintenance loop

After each bounded work unit:

1. Inspect only the owned diff and exclude unrelated working-tree changes.
2. Run focused checks plus a runtime harness, or record runtime as `N/A` with a concrete reason.
3. Record the rollback boundary and save durable facts to Engram.
4. Update agentic artifacts only when the operating contract changed.
5. Commit only when the task or repository workflow authorizes it; use one local Conventional Commit without AI attribution.
6. Never push, deploy, install services, or mutate providers without explicit authorization.
