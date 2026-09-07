# Channel setup and conversation continuity

Status: verified gaps and proposed next implementation slices, 2026-09-07.
This document does not activate providers or claim a completed history transfer.

## Verified current state

Authenticated production inspection of `/api/admin/channel-catalog` found only one
configured connection: Web, with an active route and observed traffic. The catalog
contains implemented Web and Meta WhatsApp Cloud adapters; email, Instagram DM and
Facebook Messenger are planned, not executable adapters.

| Channel | What is usable now | What is missing |
|---|---|---|
| Web | The existing SaltaCode landing/BFF integration and agent route. | A self-service installation flow, domain-to-installation model and reusable widget/snippet. |
| WhatsApp | Persisted connection credentials, route and executable Cloud API adapter. | A configured production connection, guided setup, precise field labels, callback instructions and provider acceptance. |
| Email | Catalog entry. | Provider definition, inbound/outbound adapter, verified sender/domain and setup UI. |
| Instagram DM | Catalog entry. | Executable adapter, provider permissions/configuration and acceptance. |
| Messenger | Catalog entry. | Executable adapter, provider permissions/configuration and acceptance. |

The current path is Channels → Manage connections and credentials → New connection,
followed by agent channel configuration → New route. Creation requires
`connections.manage`; routing requires `runtime.manage` and `connections.read`.
The generic form and permission-hidden actions explain part of the discoverability
problem. The current operator role was not inferred from the existence of a login.

For WhatsApp, the generic external-account field means Phone Number ID. Generic JSON
settings, separate connection/route screens, absent callback guidance and no channel
connection-test action make the existing form insufficient as guided onboarding.
Saving configuration is not proof of successful provider communication.

## Web is currently a custom integration

Creating a Web connection and route in the panel persists internal routing. It does
not publish a widget or install code on a website. The existing browser uses relative
`/api/v2/chat` URLs and same-origin session cookies. The BFF has a configured route
key and allowed origins, with protected service and cookie-signing keys outside Git.
Allowing several origins does not create separate site-to-agent mappings.

The first Web onboarding slice should explain and validate the existing deployment:
connection, receiving agent, route, public same-origin endpoint and observed traffic.
Reusable installation on other websites needs an explicit installation/domain
boundary before exposing a snippet. Never distribute the internal bearer token or
session-signing key to a browser, nor select privileged routing from arbitrary input.

## Proposed guided setup

Use one channel-specific flow rather than a generic credentials form:

1. Start from the channel card and show whether its adapter exists.
2. Collect named fields and write-only secrets appropriate to that adapter.
3. Select the receiving agent and create/validate its route in the same flow.
4. Provide exact external setup instructions and safe copyable callback information.
5. Distinguish saved, externally configured, verified and observed traffic states.

Pending adapters remain clearly unavailable; filling credentials must not imply that
an adapter was implemented. Channel-specific tests need explicit authorization and
synthetic canaries, not automatic messages to real contacts.

## Web → WhatsApp continuity

The current link is a normal `wa.me` destination. It carries no continuity proof and
does not connect the two channel identities. Runtime identities are resolved by
channel, route and external subject; recent history and historical summaries belong
to individual conversations. Existing identity-link claims record verification but
are not yet wired into cross-channel context retrieval.

The required flow is:

1. From an existing web conversation, the visitor explicitly chooses to continue
   through the configured WhatsApp channel and authorizes context continuity.
2. Issue an opaque, short-lived, one-use reference bound to that web session and
   intended channel route. Do not put the transcript or personal data in the URL.
3. Redeem the reference through authenticated inbound WhatsApp processing, with
   expiry/replay checks and explicit conflict handling for existing identities.
4. Persist the verified association and its consent/provenance. Preserve both
   channel threads rather than rewriting old messages or their authors.
5. Give the authorized agent recent messages plus retained historical context from
   the linked conversations, within access, retention and model-context limits.
6. Show the relationship in the CRM and confirm continuity to the visitor. Until
   this succeeds, do not replace the current limitation with a transfer promise.

Never merge contacts because a visitor typed a phone number or email. A proof of
channel access and an authorized memory association are distinct requirements.
Human ownership also remains authoritative: changing channels must not silently
resume a conversation paused for operator intervention.

## First external definition

Confirm whether the intended WhatsApp number is already provisioned in Meta Cloud
API or is currently used only through the phone application. That determines the
external onboarding steps; no credential, number or provider mutation is authorized
by this document. Email provider selection and social-channel permissions follow
in their own channel slices.

## Evidence anchors

- `agent-platform/panel/src/pages/Connections/index.tsx`: generic creation form,
  implemented-adapter filter and permission-gated actions.
- `agent-platform/panel/src/pages/AgentChannels/index.tsx`: agent route setup.
- `agent-platform/api/app/services/channel_catalog.py`: adapter capabilities/readiness.
- `compose.yml` and `apps/web-bff/src/app/config.py`: origin, route and server secret boundary.
- `apps/landing/src/scripts/chat-preview.ts`: WhatsApp destination and existing chat integration.
- `agent-platform/api/app/services/chat_application.py`: identity/conversation resolution.
- `agent-platform/api/app/services/conversation_memory.py`: conversation-scoped memory.
- `agent-platform/api/app/services/identity_link_claims.py`: claim verification versus runtime linking.
