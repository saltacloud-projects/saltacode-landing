# LLM-first skill style guide

Repository skills are runtime instruction contracts for an LLM. They must make activation,
non-negotiable constraints, decisions, execution, and reporting predictable without becoming
tutorials or duplicating project documentation.

## Quick path

1. Confirm the behavior is reusable and needs runtime judgment rather than ordinary documentation.
2. Create `.agents/skills/<skill-name>/SKILL.md` with the required frontmatter and section order.
3. Keep the body operational and concise; move explanations or examples to local supporting files.
4. Validate discovery metadata, decision coverage, local references, and repository registration.

## Required shape

Use these sections in order unless one is genuinely irrelevant:

| Section | Required content |
|---|---|
| Frontmatter | Discovery name, trigger-first description, license, author, and version. |
| Activation Contract | Exact situations that load the skill. |
| Hard Rules | Observable constraints the agent must not violate. |
| Decision Gates | Meaningful forks represented as a compact table or short bullets. |
| Execution Steps | Ordered actions that can be followed without hidden context. |
| Output Contract | Evidence and artifacts the final response must contain. |
| References | Stable local files only. |

Use this frontmatter shape:

```yaml
---
name: skill-name
description: "Trigger: words users or agents will say. State the runtime outcome."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---
```

The description must be one quoted, YAML-safe physical line. Put essential trigger words first,
target 160 characters or fewer, and never exceed 250 characters. Do not add a `Keywords` section.

## Writing rules

- Write imperative runtime instructions: `Map`, `Verify`, `Preserve`, `Return`.
- Make every hard rule testable or observable.
- Use decision tables only where two or more actions depend on evidence.
- Name the evidence required before a destructive, architectural, or external action.
- Keep the body between 180 and 450 tokens when practical, below 700 by default, and never above
  1,000 tokens.
- Link to project contracts instead of restating them.
- For incremental architecture skills, state what applies now and the concrete trigger for the next
  boundary or layer.

Avoid history, motivation essays, generic advice, speculative abstractions, large examples, external
URLs as primary references, and critical constraints hidden below supporting detail.

## Supporting files

- Put templates, schemas, fixtures, and executable examples in `assets/`.
- Put conceptual detail and edge cases in `references/`, pointing back to stable repository docs.
- Keep `SKILL.md` as the complete runtime entrypoint; supporting files must not hide mandatory rules.

## Versioning

Use strict Semantic Versioning (`MAJOR.MINOR.PATCH`). Increment patch for a behavioral correction or clarified safety rule, minor for a backward-compatible capability or decision gate, and major when activation or required output becomes incompatible. Do not bump versions for path-only moves, formatting, or generated-registry refreshes.

## Validation checklist

- [ ] Frontmatter is complete, trigger-first, quoted, and single-line.
- [ ] Required sections exist in the expected order.
- [ ] Activation and hard rules are concrete enough to produce consistent behavior.
- [ ] Decision gates choose actions from evidence rather than preference.
- [ ] Output requirements include validation and remaining risk where relevant.
- [ ] References are local and resolve from the skill directory.
- [ ] The skill is registered in the repository contracts and registry by the owning work unit.
- [ ] `scripts/agentic/validate-layer.sh` passes after registration.

## Review rule

Prefer a small skill that governs one repeatable decision over a broad skill that repeats the whole
agent contract. Use Git history for ordinary editorial changes that do not alter runtime behavior.
