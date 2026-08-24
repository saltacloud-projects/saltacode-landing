# Saltacode Agent Operating Contract

This repository hosts Saltacode's production landing page. Protect discoverability, conversion paths, and real-user performance before introducing new technology.

## Source of truth

- Treat the live site, provider responses, Search Console evidence, and measured field data as production truth.
- Treat `docs/discovery/initial-baseline.md` as the verified repository baseline, not proof of live behavior.
- Keep unknown deployment, DNS, Cloudflare, analytics, and indexing state explicitly unknown until verified.

## Universal guardrails

1. Start production, provider, and repository audits read-only.
2. Do not deploy, authenticate, change DNS, mutate Cloudflare, or create external resources without explicit approval.
3. Preserve public URLs, canonical intent, redirects, indexable content, contact paths, and structured data across migrations.
4. Do not claim SEO rankings or performance improvements from code inspection alone; measure before and after.
5. Keep the future AI chat outside the critical rendering path. Never expose provider secrets in browser code.
6. Prefer focused changes. Do not mix the agentic foundation, framework migration, visual redesign, and chat integration into one change.
7. Never add AI attribution or `Co-Authored-By` trailers to commits. Use conventional commits only.

## Workflow

1. Read the matching project skill before acting.
2. Use CodeGraph before broad filesystem searches for structural questions. If the repository index is unavailable, record the fallback.
3. Search Engram before repeating prior architecture or discovery work; save durable decisions and non-obvious findings.
4. Delegate only a bounded role with a clear write boundary. One writer owns overlapping files.
5. Validate locally with `scripts/agentic/validate-layer.sh` and any task-specific checks.
6. Finish each bounded work unit with `.agents/skills/delivery-checkpoint/SKILL.md`.
7. Report evidence, remaining unknowns, and potential SEO/performance impact.

## Project agents

| Agent | Access | Use |
|---|---|---|
| `repo_explorer` | Read-only | Map structure, dependencies, and change impact. |
| `seo_auditor` | Read-only | Audit crawlability, metadata, semantics, and structured data. |
| `performance_auditor` | Read-only | Audit payloads, rendering, and Core Web Vitals risks. |
| `frontend_implementer` | Workspace write | Implement an explicitly approved frontend slice and its validation. |
| `chat_integration_architect` | Read-only | Design the browser-edge-external-agent boundary. |
| `release_verifier` | Read-only | Verify a release candidate and live evidence without deploying. |

Agent definitions live in `.codex/agents/`. Do not pin agent models; inherit the parent model and reasoning effort.

## Project skills

| Skill | Trigger |
|---|---|
| `.agents/skills/production-discovery/SKILL.md` | Live or repository baseline discovery. |
| `.agents/skills/seo-regression/SKILL.md` | SEO change, migration, metadata, URL, or crawl review. |
| `.agents/skills/performance-budget/SKILL.md` | Core Web Vitals, Lighthouse, payload, or performance review. |
| `.agents/skills/asset-optimization/SKILL.md` | Image, font, CSS, or JavaScript optimization. |
| `.agents/skills/accessibility-quality/SKILL.md` | Accessibility, semantics, keyboard, or assistive technology review. |
| `.agents/skills/ai-chat-boundary/SKILL.md` | AI chat, quote flow, external agent, privacy, or secret handling. |
| `.agents/skills/cloudflare-release/SKILL.md` | Cloudflare preview, Pages configuration, production release, or rollback. |
| `.agents/skills/delivery-checkpoint/SKILL.md` | Work-unit validation, commit, rollback, or agentic maintenance. |

## Quality contract

Follow `docs/quality/seo-performance-contract.md`. Its Lighthouse targets are lab gates, not ranking guarantees. Establish a measured baseline before enforcing budgets that the current site cannot yet satisfy.

## Architecture direction

The recommended direction is documented, not implemented: Astro with TypeScript and pnpm, static-first output on Cloudflare Pages, selective islands, and an external AI-agent integration through an edge/backend boundary. Migration is a separate phase and requires explicit approval.
