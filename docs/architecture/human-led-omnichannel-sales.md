# Human-led omnichannel sales architecture

Status: active architecture contract with a dated implementation matrix below.

This document defines the commercial conversation architecture for web, WhatsApp, Instagram Direct, Facebook Messenger, and future channels. Human intervention is a core capability, not an exception path. A capability is not considered active merely because its model or adapter exists: provider configuration and production evidence remain separate gates.

## Product outcome

SaltaCode needs two initial agent responsibilities:

1. A public commercial assistant that explains verified services, qualifies intent, and requests contact data only when the visitor asks to continue toward a proposal.
2. An opportunity assistant that supports follow-up after a verified lead becomes an opportunity.

Channels are adapters to those responsibilities; they are not separate agents. Operators are independent authenticated identities with authority to inspect and control work within their granted agent scope.

The future quoting system remains authoritative for issued quotes. Model output is never a binding quote, approval, or contract.

## Repository foundation

The repository already provides:

- agent profiles with identity, prompts, provider runtime, and explicit resource bindings;
- route-scoped web and WhatsApp channel connections;
- principals, channel identities, conversations, messages, executions, retention, and audit records;
- a same-origin web BFF with origin checks, versioned consent, fail-closed rate limiting, an HttpOnly signed session, and versioned SSE events;
- authenticated WhatsApp ingress into an encrypted provider-neutral PostgreSQL queue with route/message deduplication, per-thread FIFO, leases, recovery, and review;
- an agent-scoped administration workspace;
- encrypted write-only provider credentials.

This foundation should evolve through vertical slices. It should not be replaced with one service per channel or an event-sourced rewrite.

## Implementation matrix

Snapshot: 2026-09-06 release-candidate repository state. `Implemented` means present and covered by repository checks; it does not prove that an external provider, persisted production route, or deployed image is active.

| Capability | Repository state | Activation state |
|---|---|---|
| Same-origin web chat v2, durable history, resumable events, and session reset | Implemented | Active only after the corresponding release is deployed and verified. |
| Human pause, takeover, reply, assignment, resume, and audit | Implemented for persisted conversations; web replies publish resumable events and external-channel replies use the outbox | Provider-backed behavior still requires a deployed-route check. |
| Shared outbound outbox, ordered delivery, and incident resolution | Implemented with immutable attempts/events/resolutions, route snapshots, acting-agent fences, privacy-minimized read models, and irreversible CAS/idempotent operator commands | Real WhatsApp delivery remains blocked until its persisted provider route and canary are verified. |
| Canonical authenticated provider-inbound envelope | Implemented as an encrypted provider-neutral queue with route snapshots, per-thread FIFO, leases, immutable events, and operator review | Only the WhatsApp authentication/normalization adapter is executable; Instagram Direct, Messenger, and email remain planned. Web keeps its dedicated private v2 contract. |
| Contact points, purpose-specific consent, identity-link claims, opportunities, follow-ups, and quote records | Implemented as persisted, agent-scoped commercial capabilities | Follow-up execution is implemented for an eligible verified WhatsApp route; email delivery and real provider activation remain pending. |
| Commercial contact capture from the web chat | Implemented with explicit quote-delivery consent and optional follow-up consent | Requires the deployed web/BFF/platform chain. |
| Route owner separated from acting automation agent | Implemented with versioned history and fences across web/WhatsApp execution, tools, outbox, and follow-ups | Activation still depends on deployed route/runtime evidence. |
| Follow-up operations | Implemented with worker execution, reconciliation, privacy-minimized queue/detail/events, CAS/idempotent cancel/requeue/review, RBAC, and retention-safe evidence | Only the WhatsApp delivery adapter is executable. |
| Meetings | Implemented for request, slot proposals, selection, awaiting response, manual scheduling evidence, rescheduling, cancellation, review, CAS, RBAC, audit, and panel operation | Automatic calendar scheduling remains blocked on provider selection and integration; `calendar_pending` is intentionally non-operable. |
| Instagram Direct and Messenger | Not implemented | Blocked on Meta application, permissions, secrets, callbacks, and canary evidence. |
| Authoritative quote generation | Persistence and issuance gates implemented | Blocked on the external quote-system contract and provider integration. |

## Non-negotiable invariants

1. A web session, phone number, Instagram account, and Facebook account are not automatically the same person.
2. A channel thread remains an independent conversation even when several conversations belong to one verified opportunity.
3. Human takeover must prevent every later automatic tool effect and outbound message for the affected conversation.
4. Taking over one conversation must not stop unrelated conversations.
5. External delivery uncertainty must not trigger an automatic duplicate send.
6. Browser code never receives provider secrets, privileged policies, or trusted commercial calculations.
7. A final quote may be sent only after the authoritative quote system reports an issued, versioned artifact.

## Reference topology

```text
Web                       WhatsApp          Instagram DM        Messenger
 |                            |                   |                  |
 v                            v                   v                  v
Same-origin BFF              Authenticated, route-scoped channel adapters
 |                            |
 | private web-chat v2        +-------------------+------------------+
 |                                  canonical external envelope
 |                                             |
 |                                             v
 |                              encrypted durable channel inbox
 |                              + provider deduplication and FIFO
 |                                             |
 +---------------------------------------------+
                                               |
                                               v
                                conversation application service
                        |          |              |
                        |          |              +--> contact, consent, lead,
                        |          |                   opportunity, follow-up
                        |          +--> human control kernel
                        +--> agent assignment and runtime
                                      |
                                      v
                         transactional outbound outbox
                                      |
                                      v
                       channel adapter + delivery receipts

Panel --> inbox, takeover, acting-agent assignments, opportunities,
          follow-ups, meetings, external inbound review, audit,
          delivery inspection/resolution
Quote system --> authoritative internal integration with versioned issued quotes
```

## Canonical channel boundary

Every executable external-channel adapter must normalize provider data into a versioned envelope containing:

- channel and route identity;
- provider message/thread identity;
- principal/channel-identity reference;
- received timestamp and correlation identifier;
- message kind and bounded content reference;
- consent and verification evidence available at ingress.

Provider-specific authentication and parsing remain inside adapters. The encrypted queue and conversation policy consume only the canonical contract. Duplicate provider events resolve to one accepted inbound record and one eligible execution. Web chat v2 does not use this boundary.

## Identity and consent

`Principal` and `ChannelIdentity` remain the identity root. The current relational state adds append-only verification and consent evidence without inferring cross-channel identity.

### `IdentityLinkClaim`

- source and target channel identities;
- proof method and safe evidence reference;
- pending, verified, rejected, revoked, or expired status;
- creator/verifier and expiry.

Web-to-WhatsApp linking should use a short-lived, opaque, one-time proof. Merely typing the same phone number must never merge identities.

### `ContactPoint`

- encrypted email or phone value;
- normalized lookup hash;
- verification state, source, and timestamps.

### `ConsentRecord`

- principal or provisional identity;
- purpose, legal version, channel, and locale;
- grant/revocation timestamps and correlation identifier.

Consent for answering a current request is not automatically consent for commercial follow-up on another channel.

## Human control kernel

The current-state fields live on `ChatConversation`; append-only events preserve control and acting-agent history.

### `ChatConversation` control projection

```text
id
agent_id and automation_agent_id
control_mode: automated | paused | human | closed
control_version
automation_version
assigned_admin_id
control_reason
control_changed_at
```

### `ConversationControlEvent`

```text
conversation_id
event_type: paused | taken_over | reassigned | resumed | closed
from_mode and to_mode
from_assigned_admin_id and to_assigned_admin_id
control_version
actor_admin_id
created_at
```

### `ConversationAutomationAssignmentEvent`

```text
conversation_id
routing_agent_id
from_automation_agent_id and to_automation_agent_id
automation_version
trigger and opportunity_id
actor_agent_id or actor_admin_id
idempotency_key and command_hash
created_at
```

The conversation keeps its original routing agent. Human reassignment, acting-agent handoff, and takeover do not rewrite that ownership or history. `control_version` fences human ownership changes; `automation_version` independently fences the acting automated identity.

Every control or acting-agent mutation uses optimistic concurrency. A stale `control_version` or automation epoch is rejected. The runtime revalidates `control_version`, `automation_agent_id`, and `automation_version`:

1. before starting an agent execution;
2. before a tool with external effects;
3. before creating an outbound item;
4. immediately before provider delivery.

If either epoch changed, the automatic operation becomes cancelled or review-required. It is never published. Web and WhatsApp execution paths pass the epoch guard into tool execution; queued outbound and follow-up work persist the epoch and revalidate it before provider delivery.

## Commercial lifecycle

The platform persists these commercial records:

- `Opportunity`: the commercial aggregate and lifecycle state;
- `OpportunityConversation`: explicit links to independent channel threads;
- `FollowUpTask`: scheduled action, owner, due time, policy, and outcome;
- `QuoteRequest`: requirements submitted to the authoritative system;
- `QuoteVersion`: immutable reference, status, currency, total, validity, content hash, and approval evidence.

A qualified contact plus purpose-specific consent is the current pre-opportunity state; there is no separate `Lead` aggregate yet. An opportunity begins when the visitor intentionally provides contact details for a proposal or explicitly requests continued commercial contact. If the contact route is unverified, its initial status records that fact. Persisted follow-up records do not by themselves authorize or prove automatic delivery.

## Durable outbound boundary

Automatic provider sends use the shared transactional outbox. New channel adapters must not reintroduce direct sends from conversation pipelines.

### `OutboundMessage`

```text
conversation_id
channel_route_id
agent_id
channel, adapter_key, and channel_connection_id
route_version and connection_version
sender_type and sender_admin_id
control_version
automation_agent_id and automation_version
sequence
idempotency_key and payload_hash
status
provider_message_id
correlation_id
created_at and updated_at
```

### `OutboundAttempt`

```text
outbound_message_id
attempt_number
worker_id
control_version
created_at
```

`OutboundDeliveryEvent` stores append-only transition evidence and safe result codes. Automated outbound commands snapshot both the acting-agent epoch and the exact route/connection adapter versions. Enqueue and dispatch revalidate those snapshots so a later handoff or route mutation cannot authorize stale work.

`delivery_unknown` is resolved only through an operator command with an independent `resolution_version`. Confirming delivery requires a write-only full provider message ID plus provider API or console evidence and ends in `delivered`; confirming non-delivery requires an allowlisted reason and ends in `cancelled`. Both outcomes are terminal, append immutable resolution evidence, expose only a masked provider reference, and never retry, requeue, or create another attempt.

Lifecycle:

```text
queued -> sending -> accepted -> delivered/read
                  \-> failed
                  \-> delivery_unknown
```

If a timeout occurs after the provider may have accepted the message, mark `delivery_unknown`, stop automatic retries for that conversation, and request human review. Other conversations continue.

Strict ordering is per conversation: a later item is not eligible while an earlier item is non-terminal, retrying, or delivery-unknown.

## Web contract evolution

The v2 boundary is the server-authoritative web chat contract. The v1 contract remains only where an explicit compatibility path still consumes it:

```http
POST /api/v2/chat/messages
GET  /api/v2/chat/history
GET  /api/v2/chat/events
POST /api/v2/chat/session/reset
```

- `messages` accepts an idempotent client message.
- `history` is the server authority; local browser transcript data is only a bounded cache.
- `events` resumes with `Last-Event-ID` and can deliver later human replies.
- `session/reset` rotates the anonymous session intentionally and requires CSRF protection.

Events carry `schema_version`, `event_id`, `message_id`, `correlation_id`, timestamp, actor, and cursor. Required event families include message acceptance/completion/failure, control changes, handoff state, quote state, and conversation closure.

## Panel information architecture

### Platform scope

- agents;
- shared connections, sources, tools, and knowledge resources;
- panel users and grants;

### Selected-agent workspace

- overview and identity;
- channels and routes;
- inbox;
- conversations;
- opportunities, handoffs, and automation policy;
- follow-up queue and review;
- meetings;
- external inbound review and outbound delivery inspection/resolution;
- runtime/resources;
- audit.

The current selected-agent inbox filters by channel, control mode, assignee, activity, and open/closed state. It exposes the conversation, routing and acting agents, explicit automated/paused/human status, and actions to pause, take over, reassign, reply, return to automation, or close. The human composer is enabled only when both object-scoped permission and current control allow it.

The visual agent selector is context, never authorization. Required object-scoped permissions include conversation read/manage, opportunity management, `follow_ups.read/manage/review`, `meetings.read/manage`, quote approval, inbound read/review, and delivery read/review. Delivery resolution controls appear only for `delivery_unknown` and `deliveries.review`; read-only operators see minimized evidence without mutation controls.

## Incremental delivery and activation plan

### Phase 0 — freeze current invariants (`implemented`, provider inventory pending)

- Current contracts and migration heads are pinned in tests.
- Persisted route and real provider-callback inventory remains an activation task.
- New social routes and unverified real WhatsApp traffic remain disabled.

**Gate:** repository, database, and provider state are explicitly known.

### Phase 1 — human takeover on web (`implemented in repository`)

- Conversation control, operator assignments, object-scoped grants, and append-only audit exist.
- The agent inbox and human composer exist.
- Web history and events are resumable.
- `control_version` is revalidated at the implemented automatic effect boundaries.

**Gate:** once takeover succeeds, no later automatic message or tool effect can be published.

### Phase 2 — shared outbound outbox (`implemented in repository`)

- Transactional outbound messages and immutable attempts exist.
- Current WhatsApp conversation pipelines enqueue instead of sending directly.
- Per-conversation ordering, reconciliation, and delivery-unknown review are enforced by the current outbox worker.
- Evidence-backed operator resolution terminates uncertainty as delivered or cancelled without automatic replay.

**Gate:** a simulated crash after provider acceptance cannot cause an automatic duplicate send.

### Phase 3 — WhatsApp canary (`repository path implemented; activation blocked externally`)

- WhatsApp replies already pass through human control, the provider-neutral inbound queue, and the shared outbox.
- Validate signature, deduplication, attachments, ordering, retry, uncertain delivery, and receipts against current provider behavior.
- Activate one controlled route only after acceptance evidence.

**Gate:** one canary conversation passes inbound, takeover, manual reply, resume, and delivery audit without duplication.

### Phase 4 — identity and opportunity lifecycle (`implemented in repository`)

- Verified identity-link claims, contact points, purpose-specific consent, opportunities, and follow-up-task records exist.
- Deterministic opportunity routing, acting-agent assignment history, follow-up execution, and execution/tool/outbound fencing by `automation_version` exist.

**Gate:** no cross-channel merge or follow-up occurs without evidence and valid purpose consent.

### Phase 5 — Instagram Direct and Messenger (`not implemented; blocked externally`)

- Add one authenticated adapter per channel behind the canonical envelope and outbox contracts.
- Verify provider permissions, identifiers, delivery behavior, and retention independently.

**Gate:** each channel passes the same deduplication, takeover, ordering, and privacy suite before activation.

### Phase 6 — authoritative quotes (`partial; external integration blocked`)

- Quote requests and immutable authoritative-version evidence can be stored.
- The consumer-owned port to the quote system does not exist yet.
- Delivery remains blocked unless an authoritative `issued` version exists and the channel outbox accepts it.

**Gate:** unavailable or unapproved quote data produces a retained opportunity and human handoff, never a fabricated final price.

## Acceptance suite

- Reloading or reconnecting web chat never duplicates a conversation or message.
- Concurrent takeover invalidates every pending automatic publication.
- An operator without the agent/object grant receives `403` or non-enumerating `404`.
- Repeated inbound provider events create one execution.
- A retrying earlier item blocks only its own conversation.
- Delivery uncertainty never causes automatic replay.
- Revoked consent stops future follow-up and enters the configured retention workflow.
- Cross-channel identities are never merged without verified proof.
- No credential appears in browser code, API output, logs, or audit payloads.
- No final quote is sent without an authoritative `issued` version.

## Remaining internal decisions

- Define human support hours, ownership, escalation, and response-level objectives.
- Operate a verified data-subject deletion workflow across conversations, commercial evidence, audit, backups, and processors.

## External blockers and activation evidence

- WhatsApp: persisted Meta credentials and route, callback configuration, real signed ingress, provider retry/idempotency behavior, and a delivery/read canary.
- Instagram Direct and Messenger: Meta application approval, permissions, credentials, callbacks, and canary evidence after their internal adapters exist.
- Email: selected provider, credentials, delivery semantics, and canary evidence after its internal adapter exists.
- Meetings: calendar-provider contract, OAuth/secrets, availability rules, callback/reconciliation semantics, and a real canary. Manual scheduling evidence is already available without a provider.
- Quotes: a versioned contract and integration with the future authoritative quote system. Persisting an administrator-confirmed issued version is not proof that this integration exists.
- Legal/privacy: jurisdiction-specific approval of consent wording, commercial-contact retention, processors, international transfers, and data-subject workflows.

Repository implementation does not prove production activation. These external gates block real provider-backed omnichannel automation; they do not block the dedicated web-chat v2 flow when its deployed route/runtime is independently verified.
