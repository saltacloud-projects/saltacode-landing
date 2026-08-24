# Saltacode Landing

Saltacode's production landing-page repository. The current site is a static `index.html` with checked-in assets; the new agentic foundation makes future discovery, modernization, and releases evidence-driven.

## Current scope

- Preserve the current production site while its live behavior is measured.
- Improve SEO, accessibility, and performance without breaking established URLs or contact paths.
- Prepare a separate Astro migration and a lazy AI-chat integration backed by an external agent.

No framework migration or production deployment is part of the agentic-foundation change.

## Quick path

```bash
scripts/agentic/validate-layer.sh
```

The validator checks the project Codex configuration, agent manifests, skill contracts, and required documentation without installing dependencies.

## Repository map

| Path | Purpose |
|---|---|
| `index.html` | Current production landing page source. |
| `assets/` | Current images, styles, scripts, and vendored libraries. |
| `AGENTS.md` | Repository-wide agent operating contract. |
| `.codex/` | Project Codex configuration and scoped agents. |
| `.agents/skills/` | Reusable project-specific runtime skills. |
| `docs/discovery/` | Verified baselines and known unknowns. |
| `docs/architecture/` | Technology and integration boundaries. |
| `docs/quality/` | SEO, accessibility, and performance gates. |
| `docs/agentic/` | Tool availability and operational workflow. |

## Recommended reading order

1. `docs/discovery/initial-baseline.md`
2. `docs/discovery/production-baseline.md`
3. `docs/quality/seo-performance-contract.md`
4. `docs/architecture/technology-direction.md`
5. `docs/architecture/ai-chat-boundary.md`
6. `docs/agentic/tooling.md`

## Safety

Repository evidence does not prove the live deployment, redirects, Cloudflare configuration, Search Console state, analytics, or field Core Web Vitals. Verify those systems read-only before making production claims or enforcing migration budgets.
