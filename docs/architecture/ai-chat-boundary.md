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
| External agent | Persistent consented history, agent orchestration, approved source-bound tools, channel adapters, quote workflow, and escalation. | Trusting browser-supplied identity, destination, or authorization. |

## Contract requirements

- The browser request and SSE event schemas are versioned under `contracts/chat/v1/`.
- The frontend proxy and BFF stream the response, enforce bounded timeouts, and return typed failures without exposing upstream details.
- Durable history is created only after explicit consent; the agent profile owns retention and the administration API provides controlled history access and deletion.
- Mark generated estimates as estimates until the authoritative quotation system confirms them.
- Return safe typed errors; do not expose upstream prompts, stack traces, tokens, or internal tool data.
- Propagate correlation IDs across browser, edge, agent, and business tools without logging unnecessary personal data.
- Provide a human handoff and a non-chat contact path.

## Performance and SEO isolation

Render primary marketing content without the chat bundle. Load the chat island after user intent or during idle time, reserve launcher dimensions, and measure its impact separately. Chat availability must not determine whether crawlers or visitors receive the core page.

## Security and privacy gates

Before production, verify the final privacy text, deletion workflow, retention job, provider key rotation, public abuse limits, alerting, WhatsApp credentials and access policy, and failure-mode behavior. HTTP acceptance alone does not prove the agent platform completed a quote or delivered a message.
