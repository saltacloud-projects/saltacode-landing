# Platform architecture

## Deployable units

| Unit | Responsibility |
|---|---|
| Agent API | Private execution contract, administration API, channel adapters, and health endpoints. |
| Administration panel | Configures agents, sources, tools, users, knowledge, and conversation history. |
| PostgreSQL | Durable configuration, identities, conversations, messages, executions, audit, and RAG metadata. |
| Redis | Locks, deduplication, rate support, and short-lived coordination. |
| RAG worker | Optional asynchronous document ingestion. |

## Dependency direction

Delivery adapters call application services. Application policy owns conversation and tool authorization decisions. The restricted HTTP executor and conversation-summary provider have explicit seams; the main model loop, transcription, RAG extraction, and SQLAlchemy persistence are still concrete service dependencies and must not be described as fully hexagonal.

```text
routers -> chat application -> agent loop / tool policy
                              -> conversation memory
                              -> integration source service
                                                |
                                                v
                                      restricted HTTP executor
```

New volatile boundaries should be extracted one vertical slice at a time. Empty repository layers or a wholesale rewrite would add indirection without reducing the current operational risk.

## Identity and history

A `Principal` represents a person or system. `ChannelIdentity` maps channel-specific identifiers to that principal. A `ChatConversation` belongs to one principal, one agent profile, and one channel; messages and executions remain durable and auditable.

The selected runtime controls the recent-message window, Redis history-cache TTL, summary threshold, summary size, and whether rolling summaries are enabled. Summaries are agent-scoped and advance a durable watermark in the conversation attributes; the active recent window is never folded into the summary.

Each agent profile defines its own retention window. The API enforces that policy at startup and with a periodic sweep; deleting an expired conversation cascades to its messages and execution records.

The web BFF owns its signed browser session and passes only the opaque server-side session identifier to the private execution API. WhatsApp maps the verified sender identifier through its adapter. API clients use their authenticated subject.

## Sources and tools

An `IntegrationSource` owns a base URL, host allowlist, authentication configuration, encrypted credentials, and transport policy. A `ToolConfig` points to one source and defines the relative path, HTTP method, parameter placement, input schema, permitted channels, risk, confirmation, and idempotency behavior.

This separation allows multiple APIs without environment-variable-per-source coupling and prevents the model from inventing an untrusted destination.

## Administration hierarchy

Connections, sources, tools, knowledge blocks, document areas, and reusable WhatsApp identities form platform-wide libraries. An agent owns its profile, runtime, explicit resource assignments, channel routes, conversations, and PromptLab context. A library resource is not available to an agent until its binding exists.

See [`administration-model.md`](administration-model.md) for the complete persistence, secret, routing, and panel ownership map.
