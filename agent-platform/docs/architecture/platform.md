# Platform architecture

## Deployable units

| Unit | Responsibility |
|---|---|
| Agent API | Private web-chat v2 execution, administration API, authenticated channel adapters, commercial workflows, and health endpoints. |
| Administration panel | Configures shared libraries and selected agents; operates inbox, external ingress review, opportunities, meetings, follow-ups, delivery resolution, handoffs, policy, and audit according to RBAC. |
| PostgreSQL | Durable configuration, identities, conversations, messages, executions, control events, commercial state, outbox, worker evidence, audit, and RAG metadata. |
| Redis | Locks, deduplication, rate support, and short-lived coordination. |
| Channel inbound worker | Processes the encrypted provider-neutral external inbox with per-thread FIFO; its Compose compatibility name remains `whatsapp-worker`. |
| Outbound worker | Dispatches route-snapshotted delivery intents and records provider-safe results without blind retry after uncertainty. |
| Web execution worker | Executes accepted web-chat v2 work after revalidating route, control, and acting-agent ownership. |
| Follow-up worker | Evaluates persisted commercial policy and consent, then commits outbound intent rather than calling providers directly. |
| RAG worker | Optional asynchronous document ingestion. |

## Dependency direction

Delivery adapters call application services. Application policy owns conversation and tool authorization decisions. The restricted HTTP executor and conversation-summary provider have explicit seams; the main model loop, transcription, RAG extraction, and SQLAlchemy persistence are still concrete service dependencies and must not be described as fully hexagonal.

```text
web-chat v2 router -> web execution queue -> conversation application service
external adapters -> encrypted channel inbox -> conversation application service
admin routers -> control / commercial / review application services
conversation application service -> agent loop / tool policy
                                 -> conversation memory
                                 -> integration source service
                                                   |
                                                   v
                                         restricted HTTP executor
commercial policy -> follow-up queue -> transactional outbound outbox
                                      -> outbound adapter and delivery evidence
```

New volatile boundaries should be extracted one vertical slice at a time. Empty repository layers or a wholesale rewrite would add indirection without reducing the current operational risk.

## Identity and history

A `Principal` represents a person or system. `ChannelIdentity` maps channel-specific identifiers to that principal. A `ChatConversation` belongs to one principal, one agent profile, and one channel; messages and executions remain durable and auditable.

The selected runtime controls the recent-message window, Redis history-cache TTL, summary threshold, summary size, and whether rolling summaries are enabled. Summaries are agent-scoped and advance a durable watermark in the conversation attributes; the active recent window is never folded into the summary.

Each agent profile defines its own retention window. The API enforces that policy at startup and with a periodic sweep. The sweep locks and evaluates one conversation at a time: terminal follow-ups retain historical source identifiers and event evidence while their live conversation foreign key is detached; active or uncertain follow-ups move to `review_required` and block conversation deletion. Meeting references detach through `SET NULL`. Active operational evidence is never silently deleted.

The web BFF owns its signed browser session and passes only the opaque server-side session identifier to the private web-chat v2 API. Web execution remains separate from the external-channel queue. WhatsApp maps the verified sender identifier through its adapter and commits an encrypted neutral inbound job before acknowledgement. Other external channels must implement the same authenticated envelope boundary before they become executable.

## Control and commercial orchestration

The routing agent owns the conversation. `control_version` identifies the human-control epoch, while `automation_agent_id` and `automation_version` identify the acting automation epoch. Execution, tool effects, outbound enqueue and dispatch, follow-ups, and meetings revalidate the relevant snapshots. A human takeover or acting-agent reassignment therefore fences stale work without pausing unrelated conversations.

Commercial state is persisted as append-only or versioned evidence across contacts, consent, opportunities, quote records, follow-up tasks/events, meeting records/events, outbound messages/attempts/resolutions, and audit. State-changing admin commands use semantic endpoints, deterministic idempotency, and compare-and-swap versions rather than arbitrary status setters. An uncertain delivery can only become provider-evidenced `delivered` or confirmed `cancelled`; resolution never retries or requeues the message.

Only WhatsApp has an executable external-channel adapter. Instagram Direct, Facebook Messenger, email delivery, automatic calendar scheduling, and authoritative quote issuance remain external integration work, not hidden platform behavior.

## Sources and tools

An `IntegrationSource` owns a base URL, host allowlist, authentication configuration, encrypted credentials, and transport policy. A `ToolConfig` points to one source and defines the relative path, HTTP method, parameter placement, input schema, permitted channels, risk, confirmation, and idempotency behavior.

This separation allows multiple APIs without environment-variable-per-source coupling and prevents the model from inventing an untrusted destination.

## Administration hierarchy

Connections, sources, tools, knowledge blocks, document areas, and reusable WhatsApp identities form platform-wide libraries. A routing agent owns its profile, runtime, explicit resource assignments, channel routes, conversations, commercial workspace, and PromptLab context. The acting agent is assigned explicitly per conversation. A library resource is not available to an agent until its binding exists.

See [`administration-model.md`](administration-model.md) for the complete persistence, secret, routing, and panel ownership map.
