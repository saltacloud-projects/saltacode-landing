# Technical-debt audit — 2026-09-05

## Scope and method

This audit re-evaluates the three product fronts after the 2026-08-29 remediation:

- `frontend/`: Astro landing, browser scripts, routes, styles, and generated assets;
- `backend/` and `contracts/`: public FastAPI BFF and versioned chat boundary;
- `agent-platform/`: private API, persistence, workers, integrations, and administration panel.

Code was removed only when CodeGraph, repository-wide references, dependency trees, generated output, and focused tests agreed that it had no consumer. Framework entrypoints, dynamic registrations, public compatibility routes, historical migrations, and operator scripts were not classified as dead from a missing static caller alone.

## Architecture disposition

The deployable boundaries remain appropriate for a solo maintainer: static Astro frontend, public FastAPI BFF, private agent platform, versioned contracts, and independent release units. This cleanup adds no framework, service, datastore, layer, or cross-boundary coupling.

## Cleanup completed

### Landing

- Removed the unused `brandImages.mark` API and its deterministic generation entry.
- Removed two unreferenced generated mark variants and the orphaned dark source master.
- Removed the unreferenced `.section-heading` CSS rules.
- Preserved `logo_nav_light.png` because favicon and app-icon generation consume it.

Measured repository effects:

- generated responsive asset library: 214,748 to 186,056 bytes;
- homepage CSS: 20,339 to 20,204 bytes;
- deleted tracked binaries: 137,649 bytes, including the source master;
- no public route, rendered content, metadata, visual behavior, or chat contract changed.

### BFF and contracts

No safe deletion was found. All 13 operational Python modules are reachable from `app.main`, every setting has a consumer, and the JSON contracts plus exporter participate in schema-drift checks.

The development `UnavailableAgentGateway`, strict private response fields, package markers, and SSE fields are active failure or compatibility contracts, not dead code.

### Agent platform

- Removed an unused React Query provider and dependency from the panel.
- Removed unused direct Python dependencies `tiktoken` and `respx`; the RAG chunker uses its local estimator and tests do not use `respx`.
- Removed the uncalled `GovernanceService.get_available_tools_for_user`; active tool selection belongs to `ToolPolicyService.available_tools`.
- Removed uncalled RAG and local-storage helpers, an unconsumed request schema, and an unnecessary public type export.
- Refreshed compatible panel transitive dependencies to clear the dependency-audit baseline.
- Added the operator scripts to Ruff format/lint gates and declared Pillow directly because application code imports `PIL`.

No database table, migration, persisted record, public BFF contract, agent route, or channel behavior changed.

## Retained code and evidence gates

| Candidate | Disposition | Evidence required before deletion |
|---|---|---|
| Frontend fragment aliases guarded by the build verifier | Retained compatibility | Public referrer and traffic evidence showing the historical fragments are unused. |
| BFF private response duplication | Retained debt | Introduce a cross-deployable drift test before changing either independently; current shapes match. |
| WhatsApp template, reply-button, and interactive-list senders | Retained capability | Product decision that these outbound capabilities are outside the approved channel roadmap. Templates remain relevant outside Meta's customer-service window. |
| Unkeyed WhatsApp webhook and `/webhook` mount | Retained compatibility | Current Meta callback inspection, an agreed no-traffic observation window, and rollback independence. |
| `ConversationMessage` and phone-scoped conversation service | Retained active | They are called by the compatibility WhatsApp pipeline; consolidate only after that route is retired. |
| Internal governance, audit, and tool routers | Retained unknown | Inventory any external or operator clients and observe access logs before contract retirement. |
| Panel legacy redirects | Retained compatibility | Public/operator navigation evidence and an explicit redirect-retirement window. |
| RAG import and live document verification scripts | Retained operator tools | Runbook and host-operation evidence; they are now included in the lint gate. |
| Historical Alembic migrations | Retained history | Never delete solely because application code has no caller; released databases need the chain. |

## Validation evidence

Focused validation after cleanup passed:

- frontend: Astro diagnostics, TypeScript unused checks, 10 unit tests, deterministic assets/icons, 12-page build, 11 indexable-route checks, SEO/link/security/server checks, and performance budgets;
- BFF: Ruff, contract export drift check, and 45 tests;
- Agent API: Alembic upgrade/drift, Ruff including operator scripts, dependency audit, 194 unit tests, and 5 PostgreSQL integration tests;
- Agent panel: Biome, TypeScript/Vite build, 19 Playwright tests, and npm audit with zero advisories.

These results prove the repository candidate, not current production images, external callbacks, Search Console state, rankings, or field Core Web Vitals.

## Remaining debt

1. Add a deterministic drift check for the private BFF-to-agent execution response before either side evolves independently.
2. Make the Agent API readiness description derive WhatsApp availability from persisted channel connections rather than environment variables.
3. Inventory clients of the mounted internal governance, audit, and tool routers.
4. Retire legacy WhatsApp routes only after the provider and traffic evidence gate above.

## Rollback boundaries

- Landing cleanup: revert `3f575414`.
- Agent-platform dead-code cleanup: revert `24a9a01b`.
- Operator-script quality gate: revert `a216638d`.

No production deployment, Cloudflare mutation, callback change, or database mutation was part of this audit.
