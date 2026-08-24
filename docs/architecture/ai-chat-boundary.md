# AI chat boundary

Keep the landing page responsible for presentation and consent, an edge/backend layer responsible for trust enforcement, and the existing external agent responsible for conversation and quote workflows.

## Boundary

```text
Browser chat island
  -> same-origin edge/backend endpoint
     -> authenticated external agent API
        -> approved business and quotation systems
```

The browser must never call the external agent with provider secrets or privileged credentials.

## Responsibilities

| Layer | Responsibilities | Must not own |
|---|---|---|
| Browser | Lazy UI, accessibility, consent notice, ephemeral display state, correlation ID. | Provider secrets, authorization policy, trusted pricing, unrestricted transcripts. |
| Edge/backend | Origin validation, rate limits, abuse controls, session binding, schema validation, redaction, timeouts, audit metadata, secret storage. | Marketing rendering or fabricated quote outcomes. |
| External agent | Conversation orchestration, approved tools, business rules, quote workflow, escalation. | Trusting browser-supplied identity or authorization. |

## Contract requirements

- Define versioned request and response schemas before integration.
- Stream through the boundary only when cancellation, timeout, and partial-response behavior are specified.
- Keep durable transcript storage off by default until retention, access, deletion, and consent are decided.
- Mark generated estimates as estimates until the authoritative quotation system confirms them.
- Return safe typed errors; do not expose upstream prompts, stack traces, tokens, or internal tool data.
- Propagate correlation IDs across browser, edge, agent, and business tools without logging unnecessary personal data.
- Provide a human handoff and a non-chat contact path.

## Performance and SEO isolation

Render primary marketing content without the chat bundle. Load the chat island after user intent or during idle time, reserve launcher dimensions, and measure its impact separately. Chat availability must not determine whether crawlers or visitors receive the core page.

## Security and privacy gates

Before production, complete threat modeling, rate-limit testing, prompt-injection handling, data classification, consent copy, retention policy, secret rotation, abuse monitoring, and failure-mode testing. HTTP acceptance alone does not prove the external agent completed a quote or delivered a message.
