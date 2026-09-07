# Administration and configuration model

The panel is an operator-centered multichannel CRM, not a globally selected-agent workspace.
Independent agents retain persisted identity, runtime, grants, and explicit resource bindings.
Record ownership is an authorization concern; it does not require placing daily work below
an agent selector. See [ADR 0003](../../../docs/decisions/0003-crm-first-agent-platform.md).

## Ownership hierarchy

```text
Agent Platform
├── CRM operations: inbox, opportunities, meetings, follow-ups
├── Supervision: deliveries, external ingress, audit
├── Channels: connections, readiness, ingress routes
├── Pipeline: guided progression and follow-up policy
├── Shared connection library
│   ├── model provider connections
│   ├── web and WhatsApp channel connections
│   └── external API sources with write-only credentials
├── Shared resource library
│   ├── source-bound HTTP tools
│   ├── knowledge blocks
│   ├── document areas and documents
│   └── reusable WhatsApp identities
└── Agent
    ├── profile and prompt sections
    ├── runtime and provider binding
    ├── source, tool, knowledge, document-area, and user assignments
    ├── channel routes and handoff rules
    ├── commercial progression and follow-up policy
    └── PromptLab validation context
```

Creating a resource in the shared library does not expose it to every agent. Assignment tables connect an agent to the exact sources, tools, knowledge blocks, document areas, and WhatsApp users that it may use. This keeps one reusable definition without silently sharing capabilities.

## Panel workflow

1. Open **Agents** and create a named agent with its own prompt sections. New agents are inactive;
   activation never disables another agent or creates a channel route implicitly.
2. Configure its model runtime and explicit resource bindings. Shared resources remain opt-in.
3. Open **Channels** to manage connections and choose the agent for each ingress route.
   Stored credentials and an enabled agent do not prove a working provider connection.
4. Open **Pipeline** to choose continuation or specialist handoff for quote-contact capture,
   then inspect handoff rules and follow-up limits. Validate agent behavior in PromptLab.
5. Operate the global CRM lists. Optional filters narrow authorized records; opening a row
   resolves its current command owner independently from the filter.
6. Review consent, human control, route, runtime, and provider evidence before activating an
   external channel or automation. Configuration alone does not authorize a release.

An external API source is configured in the global source library with its base URL, allowed hosts, authentication scheme, transport limits, and credentials. A tool then selects that source and defines the HTTP method, relative path, parameter placement, channel policy, risk, confirmation, and idempotency behavior. Both the source and tool must be assigned to an agent before the runtime can use them.

## Persistence and panel ownership

| Configuration | Scope | PostgreSQL | Panel/API behavior |
|---|---|---:|---|
| Provider connections | Shared | Yes | Create, update, deactivate, test; credentials are write-only. |
| Channel connections | Shared | Yes | Create, update, deactivate; WhatsApp credentials are write-only. |
| Integration sources | Shared | Yes | Create, update, deactivate, test; credentials are write-only. |
| Tools | Shared | Yes | Define a source-bound operation, then assign it to agents. |
| Knowledge blocks | Shared | Yes | Edit once, assign explicitly to agents. |
| Document areas and documents | Shared | Yes | Manage ingestion scope, assign areas explicitly to agents. |
| Agent profile | Agent | Yes | Identity, prompts, public/active state, messages, and retention. |
| Runtime | Agent | Yes | Provider binding, models, execution limits, recent-history window, Redis cache TTL, rolling-summary policy, and RAG settings. |
| Resource and WhatsApp-user assignments | Agent | Yes | Explicit many-to-many access policy. |
| Channel routes | Agent | Yes | Map one channel and `route_key` through one connection to one agent. |
| Conversations, messages, executions | Routing agent | Yes | Durable history keyed by agent, channel, route, and principal; human and acting-agent epochs fence effects. |
| Acting-agent assignments and handoffs | Routing agent and conversation | Yes | Explicit versioned reassignment; panel selection never changes execution ownership. |
| Opportunities and quote evidence | Agent | Yes | Versioned commercial state with consent/contact gates; external quote issuance remains separate. |
| Meetings | Agent | Yes | Request, proposals, response, manual schedule evidence, reschedule, cancel, and review through semantic CAS commands. |
| Follow-ups | Agent | Yes | Durable queue, event history, reconciliation, cancel/requeue/review, and retention-safe evidence. |
| Outbound deliveries | Agent | Yes | Route-snapshotted intents, attempts, receipts, safe failure codes, FIFO state, and evidence-backed resolution of uncertainty. |
| External channel inbound | Agent | Yes | Encrypted bounded payload, deduplication, per-thread FIFO, leases, safe review model, and semantic review API. |
| Commercial automation policy | Agent | Yes | Follow-up timing and kinds; no provider credentials or provider-specific rules. |
| Commercial progression policy | Ingress agent | Yes | Explicit `keep_agent` or `handoff` after valid quote-contact capture; CAS updates and audit. Missing policy preserves the legacy handoff requirement. |
| PromptLab request | Selected agent | No separate configuration record | Reads the selected persisted profile/runtime/resources; preview inputs are a validation workspace. |
| Audit log | Agent for routed activity | Yes | New routed records persist agent and channel-route ownership; selected-agent reads require `agent_id`. |
| Panel users and roles | Platform-wide | Yes | Administrative access, independent from end-user channel access. |

Conversations are not inferred from the current panel selection. Every durable conversation stores `agent_id`, `channel`, `route_key`, principal, messages, and executions, so changing the selected agent in the panel cannot move or merge history.

The conversation's routing agent and acting agent are different concerns. Human takeover advances `control_version`; acting-agent reassignment advances `automation_version`. Stale web or external-channel execution, tool effects, outbound messages, follow-ups, and meetings must revalidate their snapshots before acting.

History and summary controls are runtime behavior, not decorative panel fields. A positive cache TTL enables fail-open Redis caching for the configured recent window. Summary controls determine when older messages are compacted through the selected provider; the resulting summary and watermark remain on the agent-scoped conversation.

## Secret boundary

Source, provider, and WhatsApp credentials are submitted as write-only fields. They are encrypted before storage and API responses return only readiness such as `has_credentials`; plaintext values are never returned for editing or display.

The following remain deployment or bootstrap configuration by design:

| Setting | Why it stays outside editable business configuration |
|---|---|
| PostgreSQL DSN/password and Redis URL | The platform cannot depend on its own database to discover how to reach that database. |
| JWT signing secret | Root security material for panel sessions. |
| Source master key | Encrypts persisted connection credentials; storing it beside ciphertext would defeat the boundary. |
| Internal BFF-to-agent token | Authenticates a process boundary and is file-mounted into both deployable units. |
| Initial administrator identity/password | One-time bootstrap for an empty database; the persisted account becomes authoritative. |
| Default agent slug and bootstrap web route key | Seed an empty installation and support controlled transition; persisted agent/runtime/routes are authoritative afterwards. |
| Host names, ports, storage paths, and worker identity | Container and deployment topology rather than agent behavior. |

Provider and WhatsApp environment credentials are compatibility inputs for the idempotent bootstrap. When supplied, bootstrap imports them into encrypted persisted connections; they are not the long-term per-agent configuration interface.

## Channel routing

### Provider-neutral external ingress

Authenticated channel adapters normalize provider callbacks into one bounded versioned envelope. The platform stores its payload encrypted with an integrity hash, immutable route/connection/agent snapshots, a provider deduplication key, and a per-thread FIFO key. Worker leases and append-only events make processing recoverable; uncertain effects move to review instead of triggering a blind retry.

The global CRM collection and agent-scoped detail/command API expose privacy-minimized list,
detail, timeline, requeue, cancel, and acknowledge operations through `inbound.read` and
`inbound.review`. They do not return decrypted provider payloads or personal identifiers.

Web chat v2 is deliberately separate. It uses the private BFF contract and durable web-execution queue rather than materializing an external channel job.

### WhatsApp

The only Meta webhook is `GET|POST /webhooks/whatsapp/{route_key}`. The route key resolves a persisted WhatsApp channel connection and one agent route. The adapter verifies the connection-specific token, exact-body signature, and external account identifier before normalizing supported messages into the immutable inbound envelope. That versioned envelope carries only bounded channel, route, provider identity, content, timestamp, correlation, media-reference, and sanitized reply-reference fields. Verification and status callbacks never materialize provider credentials.

Each WhatsApp number or business route therefore needs its own channel connection and route key. The neutral durable inbox commits the encrypted envelope, route ownership, and provider idempotency key before returning an acknowledgement. Workers also read pre-envelope jobs through an in-memory compatibility decoder; no historical row is rewritten or attributed differently. WhatsApp is currently the only executable external-channel adapter.

Public agents accept a provisional channel identity backed by the conversation principal and do not create or infer an authorized-user row. Their agent loop receives `user_id=null`, so it cannot inherit private document-area grants. Private agents retain the explicit, agent-scoped WhatsApp allowlist and fail closed when the sender is absent or inactive. This policy changes identity authorization only; channel-route authentication, human-control fences, FIFO processing, tool bindings, and outbox delivery remain server-owned.

### Web BFF

The browser never selects an agent ID or route. The SaltaCode BFF owns `SALTACODE_AGENT_ROUTE_KEY` and sends it on the authenticated private execution request. The agent platform resolves that persisted public web route to one active agent, provider runtime, and web connection. Changing the browser payload cannot bypass that server-owned mapping.

## CRM reads and scoped commands

`GET /api/admin/crm/{resource}` supplies authorized cross-agent inbox, opportunities, meetings,
follow-ups, deliveries, inbound jobs, and audit collections. Permission-specific agent catalogs
do not require `profiles.read`. SQL applies scope and filters before count, ordering, and
pagination. Rows carry `owner_agent_id`, `owner_agent_name`, and effective capabilities (role
permissions intersected with active agent grants).

Details and commands remain under `/api/admin/agents/{owner_agent_id}/...` and reauthorize on
every request. Reassignment or revoked access between list and detail can cause a safe rejection
and refresh; a list response is not a durable grant.

| Collection | Current authorization owner |
|---|---|
| Inbox | Conversation routing agent, not the acting automation agent. |
| Opportunities | Current assigned agent. |
| Follow-ups and meetings | Current opportunity owner, not a task's historical assignment snapshot. |
| External ingress | Immutable routing agent snapshot. |
| Deliveries | Outbound intent owner. |
| Audit | Persisted event agent; unowned legacy records are not inferred. |

Agent configuration remains contextual under `/agents/:id/...`. Existing operational URLs stay
compatible, but the primary CRM navigation does not require selecting a working agent.

The Inbox supports conversation-level human takeover, manual response, release, and acting-agent reassignment. Meetings and follow-ups expose semantic, version-checked operations. Deliveries provides agent-scoped inspection for `deliveries.read` and irreversible uncertainty resolution for `deliveries.review`. A read-only operator sees minimized evidence without controls.

Only a `delivery_unknown` item is resolvable. `confirm_delivered` requires a write-only full provider message ID plus provider API or console evidence and ends in `delivered`. `confirm_not_delivered` requires an allowlisted reason and ends in `cancelled`. Both commands use an independent resolution CAS version and stable idempotency across uncertain network responses; neither retries, requeues, or creates another provider attempt. The panel renders only the masked provider reference after resolution.

### Internal pending work

- complete any remaining operator data-subject/erasure workflow without treating session reset as deletion.
- Complete transactional contact/consent capture for external channels: the WhatsApp contact-request
  tool currently provides instructions but does not itself record confirmed consent.
- Add event-driven commercial follow-up planning after defining its business rules. Durable task
  execution and policy exist; scheduling is currently an explicit command, not a complete autonomous planner.
- Arbitrary workflow graphs and stage editing are not implemented. Existing stage semantics and
  legal transitions remain domain code; guided policy cannot override those safeguards.

### External blockers

- Meta application approval, channel credentials, callbacks, subscriptions, and real canaries for WhatsApp, Instagram Direct, and Facebook Messenger;
- selected providers and contracts for email delivery and automatic calendar scheduling;
- authoritative quote-system API, issued-artifact contract, and delivery policy;
- final legal review of consent, privacy, retention, erasure, and cross-channel commercial contact text.

## Historical audit policy

The primary conversation model and new routed audit records are agent-scoped. Historical audit rows created before ownership was persisted keep nullable `agent_id` and `channel_route_id` values because that ownership cannot be reconstructed safely. Selected-agent reads exclude those rows; the platform does not infer or backfill an agent merely to make legacy history appear scoped.
