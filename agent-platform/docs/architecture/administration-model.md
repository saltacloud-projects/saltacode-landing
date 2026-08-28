# Administration and configuration model

The administration panel is a projection of one ownership hierarchy. Connections and reusable resources belong to the platform library; an agent becomes runnable only after it receives explicit bindings, runtime settings, and channel routes.

## Ownership hierarchy

```text
Agent Platform
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
    ├── web and WhatsApp routes
    ├── conversations, messages, and executions
    └── PromptLab validation context
```

Creating a resource in the shared library does not expose it to every agent. Assignment tables connect an agent to the exact sources, tools, knowledge blocks, document areas, and WhatsApp users that it may use. This keeps one reusable definition without silently sharing capabilities.

## Panel workflow

1. Create reusable provider, channel, and API connections in the platform library.
2. Create knowledge, document areas, and source-bound tools in the resource library.
3. Select an agent and edit its profile, runtime, assignments, channel routes, and access policy.
4. Validate that selected agent in PromptLab.
5. Review that agent's conversations before exposing or changing a public route.

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
| Runtime | Agent | Yes | Provider binding, models, limits, history, summary, and RAG settings. |
| Resource and WhatsApp-user assignments | Agent | Yes | Explicit many-to-many access policy. |
| Channel routes | Agent | Yes | Map one channel and `route_key` through one connection to one agent. |
| Conversations, messages, executions | Agent | Yes | Durable history keyed by agent, channel, route, and principal. |
| PromptLab request | Selected agent | No separate configuration record | Reads the selected persisted profile/runtime/resources; preview inputs are a validation workspace. |
| Audit log | Platform-wide today | Yes | Read-only global view because `audit_logs` does not yet persist agent ownership. |
| Panel users and roles | Platform-wide | Yes | Administrative access, independent from end-user channel access. |

Conversations are not inferred from the current panel selection. Every durable conversation stores `agent_id`, `channel`, `route_key`, principal, messages, and executions, so changing the selected agent in the panel cannot move or merge history.

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

### WhatsApp

The preferred Meta webhook is `GET|POST /webhooks/whatsapp/{route_key}`. The route key resolves a persisted WhatsApp channel connection and one agent route. The adapter verifies the connection-specific token, exact-body signature, and external account identifier before resolving provider runtime for a processable message; verification and status callbacks never materialize provider credentials.

Each WhatsApp number or business route therefore needs its own channel connection and route key. The unkeyed `/webhooks/whatsapp` endpoint is a legacy compatibility path and cannot provide deterministic multi-agent ownership.

### Web BFF

The browser never selects an agent ID or route. The SaltaCode BFF owns `SALTACODE_AGENT_ROUTE_KEY` and sends it on the authenticated private execution request. The agent platform resolves that persisted public web route to one active agent, provider runtime, and web connection. Changing the browser payload cannot bypass that server-owned mapping.

## Known ownership gap

The primary conversation model is agent-scoped, but the legacy `audit_logs` table has no `agent_id` or channel-route foreign key. Audit must remain a platform-wide view until a migration persists ownership at write time and existing records receive an explicit migration policy. UI filtering alone would not make those records agent-owned.
