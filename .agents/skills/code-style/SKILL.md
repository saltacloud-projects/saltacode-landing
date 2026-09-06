---
name: code-style
description: "Trigger: code generation, code review, formatting, imports, source organization, comments, style guide. Enforce repository coding conventions."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill before generating or reviewing any source code, tests, scripts, migrations, or configuration in this repository.

## Hard Rules

- Read the canonical coding conventions and apply the authority owned by the changed module.
- Let Ruff govern Python, Biome govern the agent panel, and Astro/TypeScript checks plus neighboring style govern the public frontend.
- Do not introduce a formatter, dependency, bulk reformat, or unrelated style churn.
- Preserve each Python module's configured line width; never normalize the BFF and Agent API to one value.
- Prefer cohesive small modules. Use regions only for stable sections in a cohesive composition, configuration, or catalog file when splitting worsens navigation; never wrap imports or narrate obvious code.
- Write new comments in English and reserve them for rationale, constraints, safety, or non-obvious contracts; do not translate unrelated existing comments.
- Report missing enforcement honestly, including the public Astro formatter gap and unavailable ShellCheck.

## Decision Gates

| Evidence | Action |
|---|---|
| Module formatter exists | Run it only on owned files and accept its output. |
| No formatter exists | Match adjacent style, apply `.editorconfig`, inspect the diff, and report the gap. |
| Organization is hard to scan | Improve names and cohesion before adding regions or layers. |
| Generated artifact changed | Update its canonical source and regenerate it; never hand-edit it. |

## Execution Steps

1. Identify changed scopes and their formatter, linter, and test authority.
2. Generate or review code against the canonical guide without touching unrelated files.
3. Run scope-native style checks, focused tests, and the complete scope gate when practical.
4. Inspect the diff for import drift, stale comments, generated files, and formatting noise.
5. Finish through `delivery-checkpoint` and record every unexecuted or unavailable enforcement step.

## Output Contract

Return affected scopes, authorities applied, commands and exact results, remaining enforcement gaps, excluded files, and rollback boundary.

## References

- `../../../docs/development/coding-conventions.md`
- `../../../.editorconfig`
- `../delivery-checkpoint/SKILL.md`
