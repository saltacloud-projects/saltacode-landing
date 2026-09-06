# AI chat boundary

Keep the landing page responsible for presentation and consent, the BFF responsible for trust enforcement, and the repository-owned `agent-platform/` service responsible for conversation and quote workflows.

## Boundary

```text
Browser chat island
  -> same-origin edge/backend endpoint
     -> authenticated agent platform API
        -> approved business and quotation systems
```

The browser must never call the agent platform with provider secrets or privileged credentials.

## Responsibilities

| Layer | Responsibilities | Must not own |
|---|---|---|
| Browser | Lazy UI, accessibility, explicit transcript consent, ephemeral display state. | Provider secrets, authorization policy, trusted pricing, or session identity. |
| Edge/backend | Origin validation, rate limits, signed HttpOnly session binding, schema validation, correlation, timeouts, safe errors, and secret storage. | Marketing rendering or fabricated quote outcomes. |
| Repository-owned Agent Platform | Persistent consented history, agent orchestration, approved source-bound tools, channel adapters, commercial records, follow-ups, meetings, quote evidence, and escalation. | Trusting browser-supplied identity, destination, agent selection, or authorization. |

## Contract requirements

- The authoritative browser request and SSE event schemas are versioned under `contracts/chat/v2/`; explicit v1 compatibility remains isolated under `contracts/chat/v1/`.
- The frontend proxy and BFF stream the response, enforce bounded timeouts, and return typed failures without exposing upstream details.
- The BFF performs only browser trust enforcement and private-contract adaptation. It does not aggregate Agent Platform resources or own commercial workflows.
- Durable history is created only after explicit consent. The agent profile owns retention; session reset is not record deletion, and erasure requests require a separately authorized data-subject workflow.
- Mark generated estimates as estimates until the authoritative quotation system confirms them.
- Return safe typed errors; do not expose upstream prompts, stack traces, tokens, or internal tool data.
- Propagate correlation IDs across browser, edge, agent, and business tools without logging unnecessary personal data.
- Provide a human handoff and a non-chat contact path.
- Fence automation and every effect with the current human-control and acting-agent versions. A stale execution must fail closed instead of sending after takeover or reassignment.

## Performance and SEO isolation

Render primary marketing content without the chat bundle. Load the chat island after user intent or during idle time, reserve launcher dimensions, and measure its impact separately. Chat availability must not determine whether crawlers or visitors receive the core page.

## Implemented internal gates

- private BFF-to-Agent authentication and server-owned web route selection;
- signed browser session, exact-origin checks, bounded schemas, rate limiting, and safe failures;
- explicit conversation consent and agent-scoped retention policy;
- human takeover, acting-agent assignment, version fences, durable outbox, follow-up and meeting evidence;
- encrypted source, provider, channel, and contact credentials or data with separate deployment keys.

## External activation blockers

Each real channel or provider requires its own credentials, route configuration, callback verification, delivery canary, alerting, and rollback evidence. Meta approval blocks WhatsApp, Instagram Direct, and Facebook Messenger activation; email and calendar need selected providers and verified contracts; authoritative quotes need the external quote-system contract. Final legal review must confirm privacy, retention, erasure, consent, and cross-channel contact text for the intended jurisdictions.

Repository implementation and HTTP acceptance do not prove a production route, completed quote, scheduled calendar event, or delivered message. Verify those outcomes against the provider and retained operational evidence before making a production-readiness claim.
