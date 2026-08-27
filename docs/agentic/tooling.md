# Agentic tooling

Use local tools to collect evidence and validate bounded work. Tool availability or authentication on this workstation does not authorize GitHub, Cloudflare, deployment, or production mutations.

## Verified local status

Checked on 2026-08-24:

| Tool | Status | Safe default |
|---|---|---|
| CodeGraph | `1.5.0`; repository index present and up to date at the check. | Explore structure and impact before broad filesystem searches. Never share an index across worktrees. |
| Engram | Available for project context, discoveries, decisions, and summaries. | Search before repeated work; save durable findings, but verify drift-prone facts against current evidence. |
| `gh` | `2.96.0`; an active local account is configured. | Use local Git by default; any GitHub API operation requires explicit task scope. |
| `cloudflared` | `2026.7.3`; binary available. | Validate sanitized config locally. Tunnel, route, DNS, service, and credential operations require explicit approval. |
| Node / pnpm | Node `24.17.0`; pnpm `11.11.0`. | Use the committed pnpm version and frozen lockfile. |
| Python / uv | Python 3.12 project target; uv `0.11.23`. | Use each Python workspace's committed lockfile. |
| Docker / Compose | Docker `29.6.2`; Compose `5.3.1`. | Validate models before starting services; use operator-owned environment and secret files. |
| Wrangler | Not installed. | It is not required by the self-hosted Tunnel topology. Add it only for an explicitly approved Workers/Pages requirement. |

Versions and authentication can drift. CI and production availability remain separate facts.

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

Compose, Tunnel-template, systemd, local probe, and public probe commands live in [`../../infrastructure/README.md`](../../infrastructure/README.md). They depend on protected operator configuration outside Git; do not substitute real secrets into documentation, logs, or committed files.

## Orchestration

1. The parent agent defines the outcome, scope, write owner, rollback boundary, and validation.
2. Read-only agents gather independent repository, SEO, performance, chat-boundary, or release evidence.
3. One implementation agent owns each overlapping file slice.
4. A fresh read-only verifier checks high-risk release evidence when warranted.
5. Engram records durable decisions and discoveries; Git history remains the code-change source of truth.

Parallelize only independent work and never assign overlapping files to multiple writers.

## Tool boundaries

- **CodeGraph:** structure, call paths, references, and blast radius. Let the watcher sync; run `codegraph sync` only if it reports stale files or the watcher is disabled.
- **Engram:** durable project memory, not a substitute for current repository or provider evidence.
- **Git/GitHub:** inspect locally first. PRs, issues, releases, settings, and branch protection changes require explicit scope even when `gh` is authenticated.
- **Cloudflare:** local template validation is not provider verification. Account, Tunnel, DNS, redirects, and production changes require explicit authorization.
- **Browser/Lighthouse:** measure a reproducible preview or deployed URL. A screenshot is visual evidence, not performance evidence.
- **Search Console:** use property-level evidence, protect identity-linked query data, and do not infer indexing from local metadata.

## Delivery maintenance loop

After each bounded work unit:

1. Inspect and stage only the owned diff; exclude unrelated working-tree changes.
2. Run focused checks plus a runtime harness, or record runtime as `N/A` with a concrete reason.
3. Record the rollback boundary and save durable facts to Engram.
4. Update agentic artifacts only when the operating contract drifted. After skill changes, refresh the skill registry and validate the layer.
5. Inspect the staged diff and create one local Conventional Commit without AI attribution.
6. Never push, deploy, install services, or mutate providers without explicit authorization.
