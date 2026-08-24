---
name: ai-chat-boundary
description: "Trigger: AI chat, quote bot, external agent, streaming, prompt injection. Design a secure, private, performance-isolated integration boundary."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill for chat UI, external-agent communication, quotes, transcript handling, streaming, tools, or human handoff.

## Hard Rules

- Never expose provider secrets, privileged credentials, authorization policy, or trusted pricing in browser code.
- Route browser traffic through a same-origin edge/backend boundary.
- Treat prompts and model output as untrusted; tools enforce authorization and schemas.
- Keep chat outside the critical rendering and indexing path.
- Do not store transcripts until consent, retention, access, and deletion are defined.

## Decision Gates

| Need | Decision |
|---|---|
| Anonymous chat | Rate limit, abuse controls, minimal session binding. |
| Personal data | Consent, classification, redaction, retention review. |
| Quote result | Mark provisional until authoritative business confirmation. |
| Streaming | Define cancellation, timeout, partial output, and reconnect behavior. |
| Agent unavailable | Preserve human contact and typed failure response. |

## Execution Steps

1. Map trust boundaries, identities, data, secrets, and authoritative systems.
2. Define versioned request, event, response, and error schemas.
3. Specify origin checks, validation, rate limits, logging, and correlation IDs.
4. Threat-model injection, tool abuse, replay, data leakage, and cost exhaustion.
5. Validate accessibility, performance isolation, failure modes, and human handoff.

## Output Contract

Return the boundary diagram, contracts, threats and controls, data lifecycle, unknowns, and production acceptance gates.

## References

- `../../../docs/architecture/ai-chat-boundary.md`
- `../../../docs/quality/seo-performance-contract.md`
