---
name: delivery-checkpoint
description: "Trigger: finish work, commit changes, delivery checkpoint, agentic maintenance. Validate and commit each bounded work unit without drift."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill when a bounded implementation, documentation, configuration, or maintenance unit is ready to deliver.

## Hard Rules

- Inspect and stage only files owned by the current work unit; never absorb unrelated changes.
- Run focused checks and a relevant runtime harness, or record runtime as `N/A` with a concrete reason.
- For frontend or visual changes, rebuild/recreate the affected active local review service and verify the served response before delivery. Never leave the review runtime on a stale image.
- State the rollback boundary before committing.
- Save durable decisions, workflows, tooling changes, fixes, and discoveries to Engram.
- Refresh agentic artifacts only when their decisions, workflows, tools, agents, or skills have drifted.
- After skill changes, refresh `.atl/skill-registry.md` and validate the layer.
- Rely on the CodeGraph watcher; run `codegraph sync` only when the watcher is disabled or reports stale files.
- Create a local Conventional Commit without AI attribution. Never push or deploy without explicit authorization.

## Decision Gates

| State | Action |
|---|---|
| Unrelated working-tree changes | Exclude them from staging and report them. |
| Focused check fails | Fix within scope or stop; do not commit a known failure. |
| Runtime boundary exists | Exercise it and record the exact result. |
| Active local review runtime serves changed UI | Refresh only the affected service, then verify health and the requested behavior from its published URL. |
| No runtime boundary | Record `N/A` and why static checks are sufficient. |
| Agentic contract drifted | Update the smallest affected skill, agent, doc, or validator. |

## Execution Steps

1. Define the completed behavior, owned files, and rollback boundary.
2. Inspect the owned diff and working tree for unrelated changes.
3. Run focused tests, refresh any active affected review service, exercise the served runtime or justify `N/A`, and run agentic validation when affected.
4. Refresh Engram, agentic artifacts, the skill registry, and CodeGraph only under their gates.
5. Stage only the work-unit files, inspect the staged diff, and create one conventional local commit.
6. Report commit, evidence, rollback boundary, exclusions, and any push or deployment still awaiting authorization.

## Output Contract

Return the work-unit scope, changed and excluded files, test and served-runtime evidence, maintenance performed, rollback boundary, and local commit hash. State explicitly that no push or deployment occurred.

## References

- `../../../AGENTS.md`
- `../../../docs/agentic/tooling.md`
- `../../../scripts/agentic/validate-layer.sh`
