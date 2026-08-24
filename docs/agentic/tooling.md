# Agentic tooling

Use tools as evidence sources with explicit mutation boundaries. Availability in one workstation session does not prove CI or production access.

## Verified local status

| Tool | Status | Safe default |
|---|---|---|
| CodeGraph | Working; a repository-local index was initialized during discovery. | Use read-only exploration and impact queries before broad searches. Ignore `.codegraph/`. |
| Engram | Working for project context, discoveries, and session summaries. | Search before repeated work; save durable decisions and non-obvious findings. |
| `gh` | Binary exists, but current authentication is invalid. | Use local Git evidence only until the user explicitly authorizes authentication. |
| Wrangler | Not installed. | Do not install or create Cloudflare resources implicitly. Add it as a pinned project dependency during the migration phase. |
| `cloudflared` | Binary exists. | Treat tunnel operations as external mutations requiring explicit approval. |

Cloudflare account, Pages project, zone, DNS, redirects, cache rules, secrets, and production deployment state are unknown. GitHub branch protection, Actions secrets, environments, and Pages integration are also unknown.

## Orchestration

1. The parent agent defines outcome, scope, write owner, and validation.
2. Read-only agents gather independent evidence for repository, SEO, performance, chat architecture, or release state.
3. One implementation agent owns an approved file slice.
4. A fresh read-only verifier checks the resulting evidence when the task warrants it.
5. Engram records durable decisions and discoveries; Git history remains the source for code changes.

The project caps spawned-agent threads at four. Parallelize only independent work and never assign overlapping files to multiple writers.

## Tool boundaries

- **CodeGraph:** structure, call paths, references, and blast radius; do not share an index across worktrees.
- **Engram:** project memory, not a substitute for current repository or production verification.
- **Git/GitHub:** inspect locally first. Authentication, PR creation, issue creation, and branch protection changes require explicit scope.
- **Cloudflare:** begin with read-only account/project inspection after authorization. Preview deployment precedes production promotion.
- **Browser/Lighthouse:** measure a real preview or deployed URL with reproducible settings; screenshots alone are not performance evidence.
- **Search Console:** use aggregated property evidence and avoid exposing identity-linked query data unnecessarily.

## Bootstrap sequence

1. Validate this layer with `scripts/agentic/validate-layer.sh`.
2. Repair `gh` authentication only if the user explicitly requests GitHub operations.
3. Discover Cloudflare state read-only after explicit authorization.
4. Add pnpm, Astro, testing, Lighthouse, and Wrangler dependencies only in the separate migration phase.

## Maintenance loop

After each bounded work unit:

1. Inspect and stage only the owned diff; exclude unrelated working-tree changes.
2. Run focused checks plus a runtime harness, or record runtime as `N/A` with a concrete reason.
3. Record the rollback boundary. Save durable facts to Engram.
4. Update skills, agents, docs, or validators only when the operating contract drifted. After skill changes, run `gentle-ai skill-registry refresh` and validate the layer.
5. Let the CodeGraph watcher synchronize changes; run `codegraph sync` only when the watcher is disabled or reports stale files.
6. Inspect the staged diff and create one local Conventional Commit. Never add AI attribution, push, or deploy without explicit authorization.
