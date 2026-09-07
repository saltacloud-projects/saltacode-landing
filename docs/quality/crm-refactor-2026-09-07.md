# CRM-first refactor verification — 2026-09-07

## Outcome

Implemented the operator-centered CRM navigation and authorized cross-agent read boundary,
independent agent creation, channel configuration entrypoint, and explicit commercial progression.
This is repository and isolated-review evidence, **not a production release**. No push, production
restart, DNS change, external provider activation, or production database migration occurred.

Decision: [ADR 0003](../decisions/0003-crm-first-agent-platform.md).
Operation and persistence map:
[administration model](../../agent-platform/docs/architecture/administration-model.md).

## Verified behavior

| Area | Evidence |
|---|---|
| CRM reads | Seven collections authorize before SQL count/pagination; permission-specific catalogs and per-record owner/capabilities. |
| Ownership | Routing, acting agent, current opportunity owner, task snapshot, and human operator remain distinct. |
| Agents | Visible creation workflow creates an inactive independent agent with its own prompts and creator grant; activating one does not disable others. |
| Channels | Separate configuration hub distinguishes stored connections, implemented adapters, routing, and actual external activation. |
| Progression | Explicit `keep_agent` or `handoff`; absent configuration preserves legacy behavior. Same-agent capture preserves automated, paused, and human-owned states. |
| Replay | Completed opportunity receipt wins over later policy or route changes. |
| Tool effects | Contact-request tool works after acting-agent handoff; stale control/automation versions fail closed. Public event ownership stays on the routing agent. |
| Isolation fixes | Legacy audit requires grants; no global phone-name lookup; same principal does not authorize new foreign-agent conversation links. |
| Development | Vite requires explicit `PANEL_API_TARGET`; removed the inherited port 8001 target observed to belong to another production project. |

## Validation

`pnpm verify` passed across the unchanged public landing/BFF, Agent API, panel, infrastructure,
and agentic contracts:

- BFF: 97 tests.
- Agent API: 420 non-integration tests and 148 PostgreSQL integration tests.
- Panel: Biome, TypeScript, Vite build, and 86 Playwright E2E tests at the main checkpoint.
- Empty database upgrade, prior revision upgrade/data preservation, and Alembic drift check.
- Security dependency audits, Compose fixtures, shell syntax, and agentic validation.

The regular panel E2E suite uses mocked API responses. Separately, a browser against the actual
API and an isolated PostgreSQL database verified login, UI agent creation, policy update and
persistence after reload, global inbox takeover, operator reply/history reload, and explicit
resumption. No page errors or HTTP 5xx were observed along those paths. A 390-pixel mobile
channel view had no horizontal overflow; screenshots were inspected outside version control.

The isolated review has no real provider credentials, customer data, or active outbound workers.
It is temporary and must not be used as a production database or a migration backup. The production
panel remains unchanged until an explicitly authorized release.

Known validation limits: no physical-device or screen-reader session; no production/provider
canaries; ShellCheck unavailable locally. Existing dependency deprecation and Alembic computed
search-vector warnings remain visible; no schema drift was detected. The public Astro surface
still has no dedicated formatter. No SEO ranking or field-performance improvement is claimed.

## Schema and rollback

New head: `f14e8c0f2a56`, following `f13d7b9e1f45`. The migration only adds
`commercial_progression_policies`; it does not backfill configuration or rewrite history.
Downgrade is allowed only while that table is empty and refuses to discard saved policy.
Deployment must migrate the API before serving the new panel's CRM endpoints. Preserve the
existing production backup/receipt and application-schema compatibility procedures; never restore
an old database as an application rollback.

## Explicitly remaining

- External-channel contact/consent capture is not complete; WhatsApp's contact-request tool
  currently returns guidance rather than recording consent on its own.
- Commercial follow-up scheduling is still an explicit command, not a complete event-driven
  autonomous sales planner. Timing/limits and durable execution are already persisted.
- Instagram/Messenger/email adapters, automatic calendar integration, and authoritative quote
  issuance require implementation and provider contracts/credentials/activation evidence.
- Arbitrary workflow graphs and editable domain stages are intentionally not introduced.
- A data-subject/erasure workflow and final legal review remain separate work.

Public landing assets, URLs, rendering code, and public BFF contracts were not changed by this
refactor. Production SEO/performance effects cannot be inferred from these local checks.
