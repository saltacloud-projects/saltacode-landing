# Coding conventions

This guide is the canonical code-style contract for authored source, tests, scripts, and
configuration in this repository. Apply it to every generated change and every code review.
Automated module-local tools take precedence over prose and `.editorconfig` when they disagree.
Do not use this guide as a reason to reformat unrelated files.

## Formatter authority

| Scope | Authority | Line width | Notes |
|---|---|---:|---|
| `apps/web-bff/` Python | Ruff from `apps/web-bff/pyproject.toml` | 100 | Ruff format and import sorting are authoritative. |
| `agent-platform/api/` Python | Ruff from `agent-platform/api/pyproject.toml` | 88 | Keep this module-local width; do not normalize it to the BFF. |
| `agent-platform/panel/` | Biome from `agent-platform/panel/biome.jsonc` | 100 | Biome owns formatting, linting, and import organization under `src/`. |
| `apps/landing/` Astro and TypeScript | Astro/TypeScript checks plus neighboring style | No automated formatter | The public frontend has no formatter or linter configured. Preserve local style and report this automation gap during review. |
| Shell | `bash -n`; ShellCheck when available | N/A | CI pins ShellCheck; local availability is not guaranteed, so report when it could not run. |

`.editorconfig` establishes only portable whitespace defaults. It does not replace Ruff, Biome,
Astro, TypeScript, or shell analysis. Never add a formatter, dependency, or repository-wide
reformat as an incidental part of another change.

## Whitespace and visual layout

- Use UTF-8, LF endings, a final newline, and no trailing whitespace except intentional Markdown
  hard breaks.
- Use spaces: four for Python and two for web and supported configuration files. Make recipes use
  tabs.
- Let the owning formatter decide wrapping. Where no formatter exists, keep expressions readable,
  follow adjacent code, and avoid manual column alignment that creates noisy diffs.
- Use blank lines to reveal meaningful boundaries, not to separate every statement. Keep related
  declarations together.
- Prefer an early return or a named helper over deeply nested or visually compressed logic.

## Import ordering

### Python

Let Ruff's `I` rules organize imports into standard-library, third-party, and application groups,
with one blank line between groups. Import from the owning public module, remove unused imports,
and avoid wildcard imports. Use `TYPE_CHECKING` only to solve a real runtime dependency or import
cycle.

### TypeScript, JavaScript, and Astro

In the administration panel, let Biome organize imports. Elsewhere, preserve side-effect order and
follow the local sequence: platform or external modules, repository modules, then relative modules.
Use `import type` for type-only dependencies when supported. Keep stylesheet and other side-effect
imports explicit; do not move them merely to make groups look uniform.

Do not wrap imports in region markers or annotate obvious import groups with comments.

## Source organization

- Prefer small cohesive modules with one clear reason to change. Split by responsibility only when
  the extracted unit has a real owner, policy, dependency boundary, or useful test seam.
- Keep entrypoints and composition roots focused on wiring. Keep business rules out of route,
  framework, and provider adapters.
- Place declarations in the order that makes the file readable: public contract or primary entry
  first when practical, followed by supporting private details. Match framework-required ordering
  when it is more predictable.
- Keep constants close to their owner. Do not create miscellaneous `utils`, generic base classes,
  pass-through services, empty layers, or speculative folders.
- Use region markers only in a cohesive composition, configuration, or catalog file containing
  several stable sections when splitting the file would make navigation worse. Regions must name
  durable responsibilities, not individual functions. Never region-wrap imports or use decorative
  separator comments.

The attached region-based example is guidance about logical grouping, not a template to reproduce
throughout the codebase. Cohesion is more important than visual ceremony.

## Naming

- Name by business or operational intent, not implementation accident. Prefer precise domain terms
  already established in the owning module.
- Use `snake_case` for Python functions and variables and `PascalCase` for Python classes and
  protocols. Use `UPPER_SNAKE_CASE` only for true constants.
- Use `camelCase` for TypeScript/JavaScript values and functions and `PascalCase` for components,
  classes, and types. Follow neighboring filename conventions rather than renaming an existing tree.
- Name boolean values as predicates (`isReady`, `hasConsent`, `canResume`). Avoid unexplained
  abbreviations, redundant type words, and catch-all names such as `data`, `manager`, or `helper`
  when a specific role is known.
- Tests should describe observable behavior and condition, not repeat an implementation method
  name without context.

## Comments and documentation

- Write new technical comments and docstrings in English. Preserve existing-language comments
  unless the edited behavior makes them inaccurate or the owned file is intentionally normalized.
  User-facing copy follows the product language and is not governed by this rule.
- Explain why a constraint, tradeoff, compatibility rule, or safety boundary exists. Do not narrate
  what the next line already says.
- Prefer clearer names and smaller cohesive code over explanatory comments. Delete stale comments
  in the same work unit that makes them false.
- Add docstrings or JSDoc to public or non-obvious contracts when callers need behavior, failure,
  ownership, or side-effect information. Do not document every private helper mechanically.
- `TODO` and `FIXME` must state the missing outcome and a trackable issue or activation condition;
  they are not substitutes for completing the current work unit.
- Never place secrets, personal data, access tokens, or sensitive production examples in comments,
  fixtures, documentation, or generated output.

## Tests

- Add or update the smallest test that proves changed behavior. Keep tests in the same work unit as
  their implementation.
- Test public outcomes and important boundary failures; avoid coupling tests to private line-by-line
  implementation unless the unit itself is the contract.
- Keep tests deterministic. Control time, randomness, network, and persistent state explicitly.
- Prefer small named fixtures and builders over large inline payloads. Do not hide the behavior under
  test behind generalized setup machinery.
- Use Arrange/Act/Assert comments only when the phases are genuinely difficult to see.

## Generated files

- Do not hand-edit generated artifacts. Change the canonical source or generator, regenerate, and
  run its drift check.
- Keep generated artifacts only when the runtime or release process requires them in Git. Do not
  introduce generated caches, build output, bytecode, dependency directories, or local secrets.
- Review generated diffs for unexpected contract, asset, or metadata changes even when a generator
  produced them.

## Review checklist

- [ ] The change follows the formatter and line width owned by its module.
- [ ] Imports are ordered by the owning tool or the documented local fallback.
- [ ] Names and module boundaries communicate responsibility without speculative abstractions.
- [ ] Comments explain constraints or rationale and contain no sensitive information.
- [ ] Tests cover the changed behavior and relevant boundary failures.
- [ ] Generated files came from their canonical generator and pass drift checks.
- [ ] The diff contains no unrelated formatting churn, dead code, or stale comments.
- [ ] Scope-native checks ran; unavailable or missing enforcement was reported explicitly.

## Scope verification

Run the smallest relevant style command while iterating, then the complete scope gate before the
delivery checkpoint.

| Scope | Style command | Complete scope gate |
|---|---|---|
| Public frontend | No formatter is configured; inspect the diff and run Astro checks | `pnpm verify:frontend` |
| BFF | `cd apps/web-bff && uv run --locked ruff format . && uv run --locked ruff check .` | `pnpm verify:backend` |
| Agent API | `cd agent-platform/api && uv run --locked ruff format app tests scripts && uv run --locked ruff check app tests scripts` | `pnpm verify:agent-api` |
| Agent panel | `cd agent-platform/panel && npm run check:write` | `pnpm verify:agent-panel` |
| Infrastructure and shell | Run `bash -n` on every changed Bash file and `shellcheck <changed-files>` when available | `pnpm verify:infrastructure` |
| Agentic contracts | Inspect Markdown/YAML diffs and validate references | `pnpm verify:agentic` |
| Cross-cutting change | Run each affected scope first | `pnpm verify` |

Formatter write commands may modify files. Inspect their diff before continuing. If a complete gate
requires unavailable infrastructure or tooling, run every available focused check and report the
exact enforcement gap; never claim an unexecuted check passed.
