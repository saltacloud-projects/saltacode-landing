# Human-led omnichannel sales architecture

Status: proposed roadmap, not an implemented runtime contract.

This document turns the current SaltaCode agent platform into an incremental plan for commercial conversations across web, WhatsApp, Instagram Direct, and Facebook Messenger. Human intervention is a core capability, not an exception path.

## Product outcome

SaltaCode needs two initial agent responsibilities:

1. A public commercial assistant that explains verified services, qualifies intent, and requests contact data only when the visitor asks to continue toward a proposal.
2. An opportunity assistant that supports follow-up after a verified lead becomes an opportunity.

Channels are adapters to those responsibilities; they are not separate agents. Operators are independent authenticated identities with authority to inspect and control work within their granted agent scope.

The future quoting system remains authoritative for issued quotes. Model output is never a binding quote, approval, or contract.

## Existing foundation

The repository already provides:

- agent profiles with identity, prompts, provider runtime, and explicit resource bindings;
- route-scoped web and WhatsApp channel connections;
- principals, channel identities, conversations, messages, executions, retention, and audit records;
- a same-origin web BFF with origin checks, versioned consent, fail-closed rate limiting, an HttpOnly signed session, and versioned SSE events;
- authenticated WhatsApp ingress with a PostgreSQL inbox, route/message deduplication, leases, recovery, and bounded retry;
- an agent-scoped administration workspace;
- encrypted write-only provider credentials.

This foundation should evolve through vertical slices. It should not be replaced with one service per channel or an event-sourced rewrite.

## Non-negotiable invariants

1. A web session, phone number, Instagram account, and Facebook account are not automatically the same person.
2. A channel thread remains an independent conversation even when several conversations belong to one verified opportunity.
3. Human takeover must prevent every later automatic tool effect and outbound message for the affected conversation.
4. Taking over one conversation must not stop unrelated conversations.
5. External delivery uncertainty must not trigger an automatic duplicate send.
6. Browser code never receives provider secrets, privileged policies, or trusted commercial calculations.
7. A final quote may be sent only after the authoritative quote system reports an issued, versioned artifact.

## Target topology

```text
Web              WhatsApp          Instagram DM        Messenger
 |                   |                   |                  |
 v                   v                   v                  v
Same-origin BFF      Authenticated, route-scoped channel adapters
 |                   |
 +-------------------+-------------------+------------------+
                         canonical inbound envelope
                                      |
                                      v
                     durable inbox + provider deduplication
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

Panel --> inbox, takeover, assignments, opportunities, audit, delivery review
Quote system --> authoritative internal integration with versioned issued quotes
```

## Canonical channel boundary

Every inbound adapter should normalize provider data into a versioned envelope containing:

- channel and route identity;
- provider message/thread identity;
- principal/channel-identity reference;
- received timestamp and correlation identifier;
- message kind and bounded content reference;
- consent and verification evidence available at ingress.

Provider-specific payloads remain inside adapters. Conversation policy consumes only the canonical contract. Duplicate provider events must resolve to one accepted inbound record and one eligible execution.

## Identity and consent

Keep `Principal` and `ChannelIdentity`. Add relational state plus append-only evidence:

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

### `ConsentReceipt`

- principal or provisional identity;
- purpose, legal version, channel, and locale;
- grant/revocation timestamps and correlation identifier.

Consent for answering a current request is not automatically consent for commercial follow-up on another channel.

## Human control kernel

Add one current-state record and append-only assignments/audit events.

### `ConversationControl`

```text
conversation_id
mode: automated | paused | human
control_version
assigned_operator_id
reason
paused_at
resumed_at
updated_at
```

### `ConversationAssignment`

```text
conversation_id
subject_type: agent | operator
subject_id
role
valid_from
valid_until
assigned_by
```

The conversation keeps its original owning agent. Reassignment and takeover do not rewrite history.

Every control mutation uses optimistic concurrency. A stale `control_version` returns `409 Conflict`. The runtime revalidates that version:

1. before starting an agent execution;
2. before a tool with external effects;
3. before creating an outbound item;
4. immediately before provider delivery.

If the version changed, the automatic operation becomes cancelled or review-required. It is never published.

## Commercial lifecycle

Add only when the takeover slice is stable:

- `Lead`: qualified interest without assuming a verified contact route;
- `Opportunity`: the commercial aggregate and lifecycle state;
- `OpportunityConversation`: explicit links to independent channel threads;
- `FollowUpTask`: scheduled action, owner, due time, policy, and outcome;
- `QuoteRequest`: requirements submitted to the authoritative system;
- `QuoteVersion`: immutable reference, status, currency, total, validity, content hash, and approval evidence.

An opportunity begins when the visitor intentionally provides contact details for a proposal or explicitly requests continued commercial contact. If the contact route is unverified, its initial status records that fact.

## Durable outbound boundary

Direct sends from pipelines must be replaced with a shared transactional outbox.

### `OutboundMessage`

```text
conversation_id
channel_route_id
actor_type and actor_id
control_version
idempotency_key and payload_hash
status
provider_message_id
correlation_id
created_at and updated_at
```

### `OutboundAttempt`

```text
outbound_message_id
attempt
started_at and completed_at
safe result/error code
```

Lifecycle:

```text
queued -> sending -> accepted -> delivered/read
                  \-> failed
                  \-> delivery_unknown
```

If a timeout occurs after the provider may have accepted the message, mark `delivery_unknown`, stop automatic retries for that conversation, and request human review. Other conversations continue.

Strict ordering is per conversation: a later item is not eligible while an earlier item is non-terminal, retrying, or delivery-unknown.

## Web contract evolution

The current v1 contract remains compatible during the first migration. Human replies after the original request require a resumable v2 boundary:

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
- global delivery incidents and outbox review.

### Selected-agent workspace

- overview and identity;
- channels and routes;
- inbox;
- conversations;
- opportunities and follow-ups;
- runtime/resources;
- audit.

The inbox needs filters by agent, channel, state, and assignee; a conversation view; commercial context; explicit automated/paused/human status; delivery receipts; and actions to pause, take over, assign, reply, return to automation, or close. The human composer is enabled only when both object-scoped permission and current control allow it.

The visual agent selector is context, never authorization. Required object-scoped permissions include conversation read/takeover/reply/assign/resume, opportunity management, quote approval, and delivery review.

## Delivery plan

### Phase 0 — freeze current invariants

- Pin current contracts and migration heads in tests.
- Inventory persisted routes and real provider callbacks before activation.
- Keep new social routes and real WhatsApp traffic disabled.

**Gate:** repository, database, and provider state are explicitly known.

### Phase 1 — human takeover on web

- Add conversation control, assignments, object-scoped grants, and append-only audit.
- Add the agent inbox and human composer.
- Introduce resumable web history/events.
- Revalidate `control_version` at every automatic effect boundary.

**Gate:** once takeover succeeds, no later automatic message or tool effect can be published.

### Phase 2 — shared outbound outbox

- Add transactional outbound messages and attempts.
- Remove direct provider sends from pipelines.
- Enforce per-conversation ordering, reconciliation, and delivery-unknown review.

**Gate:** a simulated crash after provider acceptance cannot cause an automatic duplicate send.

### Phase 3 — WhatsApp canary

- Route WhatsApp replies through human control and the shared outbox.
- Validate signature, deduplication, attachments, ordering, retry, uncertain delivery, and receipts against current provider behavior.
- Activate one controlled route only after acceptance evidence.

**Gate:** one canary conversation passes inbound, takeover, manual reply, resume, and delivery audit without duplication.

### Phase 4 — identity and opportunity lifecycle

- Add verified identity links, contact points, purpose-specific consent, leads, opportunities, and follow-up tasks.
- Add the handoff from public commercial assistant to opportunity assistant.

**Gate:** no cross-channel merge or follow-up occurs without evidence and valid purpose consent.

### Phase 5 — Instagram Direct and Messenger

- Add one authenticated adapter per channel behind the canonical envelope and outbox contracts.
- Verify provider permissions, identifiers, delivery behavior, and retention independently.

**Gate:** each channel passes the same deduplication, takeover, ordering, and privacy suite before activation.

### Phase 6 — authoritative quotes

- Add a consumer-owned port to the quote system.
- Store immutable quote versions and approval evidence.
- Allow delivery only for `issued` versions through the outbox.

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

## Decisions required before activation

- Provider-specific retry and idempotency behavior for each Meta API.
- Final policy and operator workflow for `delivery_unknown`.
- Purpose-specific legal wording and retention for commercial follow-up.
- Human support hours, ownership, and response-level objectives.
- Versioned contract of the future quote system.

These decisions do not block the current web-chat continuity improvement. They block real omnichannel automation and outbound activation.
