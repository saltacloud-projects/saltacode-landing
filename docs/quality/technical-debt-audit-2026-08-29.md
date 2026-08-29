# Technical-debt audit — 2026-08-29

## Outcome

The repository has a viable architecture for a solo maintainer. The reviewed debt does not justify a rewrite: the correct direction is to preserve the current deployable boundaries, keep their contracts explicit, and extract capabilities only when verified coupling makes that necessary.

The bounded code-debt remediation is complete and the root verification gate passes. This does **not** mean that the product has no future work. The remaining items are production evidence, compatibility-retirement decisions, credential rotation, and professional legal review rather than unidentified dead code or an unresolved architectural foundation.

## Current architecture

| Deployable or boundary | Responsibility | Persistence and coupling |
|---|---|---|
| `frontend/` | Static-first Astro site, indexable content, deferred chat UI, theme and navigation. | No provider secrets or durable chat state; calls the same-origin BFF contract. |
| `backend/` | Public FastAPI BFF for origin checks, consent, session identity, rate limiting, contract adaptation, and SSE. | Ephemeral Redis rate limits; private authenticated call to one persisted agent route. |
| `agent-platform/fastapi/` | Multi-agent runtime, channel routing, encrypted connections, tools, RAG, conversation history, audit, and provider orchestration. | PostgreSQL and internal Redis; no direct browser trust. |
| `agent-platform/frontend/` | Administration panel organized around shared resource libraries and a selected agent workspace. | Uses the Agent API; credentials remain write-only. |
| `contracts/` | Versioned browser-to-BFF and BFF-to-agent schemas. | Prevents either deployable from depending on internal implementation details. |
| `compose.yml` and `infrastructure/` | Independent site and agent release units plus the private bridge and host-managed Tunnel routing. | Site rollback does not reset agent data; agent rollback does not rebuild the landing. |

The dependency direction is appropriate: the public site depends on contracts and the BFF, while the BFF depends on a private agent contract rather than the agent database or panel. See [`../architecture/platform-topology.md`](../architecture/platform-topology.md) for the trust and network boundaries.

## Debt resolved in this workstream

| Area | Resolution | Evidence |
|---|---|---|
| Orphaned frontend assets and repeated metadata | Removed unused assets and centralized page metadata. | `1c595bcd` |
| Service-image masters | Normalized oversized masters while preserving deterministic responsive variants. | `f96fe6ed` |
| Chat maintainability | Split DOM orchestration, presentation, template, and pure SSE parsing; added protocol unit tests and retained deferred loading. | `8d0f66ed` |
| Disconnected agent defaults and metrics | Removed unused panel/API configuration surfaces rather than preserving decorative settings. | `7ccc2ff1` |
| Quota persistence | Removed a persistence path that was not connected to effective runtime policy. | `76ae69c0` |
| Conversation memory controls | Connected persisted history, cache, summary, and watermark controls to runtime behavior. | `d84e40db` |
| Audit ownership | Persisted new agent and route ownership, required selected-agent reads, and kept unverifiable history unassigned. | `d8712813` |
| Duplicate database uniqueness | Removed redundant unnamed slug constraints while retaining the named unique indexes; Alembic reports no drift. | `88fd88f3` |
| Agent panel quality | Added one pinned Biome gate and fixed real formatting, accessibility, React hook, button, key, and assertion issues. | `c508ff99` |
| Runtime readiness and supply-chain gates | Hardened readiness secrets/runtime image and added deterministic migration, dependency, build, E2E, and audit gates. | `9e280407`, `6dd7b94f` |
| Release and rollback | Added independent immutable agent releases with migrations, health checks, secret-free receipts, and fail-closed rollback compatibility. | `3b81a854` |

## Dead-code disposition

Deletion requires evidence, not a name or a missing import alone.

| Candidate | Disposition | Reason |
|---|---|---|
| Old admin metrics, agent defaults, quota storage, and orphaned assets | Removed | Their UI, API, persistence, or asset paths were disconnected from effective behavior. |
| `ConversationMessage` and `app/services/conversation.py` | Retained as active | The WhatsApp pipeline calls them for durable recent history and rolling summaries. They are a consolidation candidate only if all channels later converge on one conversation path. |
| `GET|POST /webhooks/whatsapp/{route_key}` | Retained as primary | This is the persisted, deterministic multi-agent WhatsApp route. |
| Unkeyed `/webhooks/whatsapp` and singular `/webhook` mount | Retained as compatibility | Repository code labels the unkeyed route as legacy, but current Meta callback configuration and live traffic evidence are required before removal. |
| `import_rag_corpus.py` and `verify_documents_live.py` | Retained as operator tools | Static references cannot prove whether host runbooks or manual operations use them. Remove only after checking operational history and documentation. |
| Metalnor client marks in public site content | Retained as legitimate content | No Metalnor, Scrappy, SIM, or GeneXus business logic remains in the agent platform; the public mark represents an actual listed SaltaCode client. |

### Compatibility retirement gate

Remove a compatibility route or operator script only when all of the following are true:

1. the production callback/runbook points to its replacement;
2. an agreed observation window shows no calls or invocations;
3. the rollback procedure no longer depends on it; and
4. contract, integration, and deployed-response checks pass after removal.

This is intentionally stricter than deleting files that appear unused from a local search.

## Verification evidence

The 2026-08-29 root `pnpm verify` gate passed after the code remediation:

- frontend: Astro diagnostics `0`, five chat-stream unit tests, deterministic assets/icons, build, SEO, link, and server checks;
- BFF: Ruff and `45` tests;
- Agent API: migrations to the current head, Alembic drift check with no new operations, Ruff, dependency audit with zero known vulnerabilities, `178` unit tests, and `4` PostgreSQL integration tests;
- Agent panel: Biome with zero diagnostics, production build, `19` E2E tests, and npm audit with zero known vulnerabilities;
- infrastructure: isolated sandbox release preflight;
- agentic layer: six agent definitions and ten project skills validated.

The latest deterministic frontend build remained inside every repository budget:

| Asset | Result | Limit |
|---|---:|---:|
| Home HTML | 29,845 bytes | 29,952 bytes |
| Homepage CSS | 20,339 bytes | 20,480 bytes |
| Interior-only CSS | 5,076 bytes | 5,120 bytes |
| Initial JavaScript | 5,410 bytes | 5,632 bytes |
| Non-chat JavaScript | 6,747 bytes | 7,168 bytes |
| Deferred chat | 16,235 bytes | 16,384 bytes |
| Deferred privacy JavaScript | 1,789 bytes | 3,072 bytes |
| Deferred privacy CSS | 3,752 bytes | 4,096 bytes |
| Social image | 20,640 bytes | 102,400 bytes |
| Webfonts | 0 bytes | 0 bytes |
| Responsive image library | 214,748 bytes | 266,240 bytes |

These are repository and local-lab gates. They do not prove rankings, public cache behavior, or field Core Web Vitals.

## Remaining gates and ownership

| Gate | Why it remains | Owner/action |
|---|---|---|
| Rotate the external credential exposed in local command output | A secret must be considered compromised after appearing in terminal/tool output, even when it was not committed. | Operator rotates it before a real release and updates the protected secret source. Never store its value in documentation or receipts. |
| Verify Meta callbacks before deleting legacy webhook paths | Local code cannot establish the callback URL currently configured at Meta or whether old paths still receive traffic. | Operator provides or authorizes inspection of current provider configuration and an observation window. |
| Public SEO and field performance evidence | Build checks cannot establish indexing, rankings, Cloudflare cache/compression, Search Console state, or 75th-percentile Core Web Vitals. | Run the release evidence plan after an authorized deployment; compare against the dated baseline. |
| Legal review | The repository can implement consent, privacy controls, and policy pages but cannot certify worldwide legal compliance. | Qualified counsel reviews the final business identity, processors, retention, jurisdiction, and policy text. |
| Push and production deployment | Local commits and checks are not authorization to mutate the remote or production. | Operator explicitly authorizes the release scope. |

## Maintenance rule

Keep one root gate (`pnpm verify`) as the release-candidate contract, and keep every change as a bounded conventional commit. Do not add a second framework, service, datastore, or abstraction because it is modern; add it only when measured constraints cannot be satisfied inside the existing boundary. Revisit this audit when a compatibility path is retired, a deployable boundary changes, or production evidence invalidates a current assumption.
