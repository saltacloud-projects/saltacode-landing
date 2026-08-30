---
name: backend-api-quality
description: "Trigger: FastAPI, BFF, HTTP API, SSE, backend contract. Evolve server boundaries safely with explicit failure and compatibility semantics."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill for FastAPI routes, BFF behavior, HTTP/SSE contracts, middleware policy, internal adapters, or API compatibility changes.

## Hard Rules

- Treat schemas, status codes, content types, headers, event ordering, and terminal events as public contracts.
- Validate bounded input at ingress; resolve server-owned identity and authorize before invoking policy or external work.
- Keep rate limits fail-closed and ahead of expensive execution; test the intended ordering of validation, session creation, and limiter consumption.
- Bound connection, response, and overall work; propagate client disconnect and cancellation so upstream tasks do not outlive requests.
- Before SSE starts, return typed HTTP problems; after it starts, emit the versioned error and exactly one terminal event without leaking upstream details.
- Require idempotency or replay protection when retries can repeat writes; do not add ceremonial idempotency to safe reads.
- Add ports only for evidenced volatility or a valuable test seam; never create empty layers or generic repositories.

## Decision Gates

| Evidence | Action |
|---|---|
| Additive compatible field | Preserve defaults and verify old consumers. |
| Breaking request, response, or event change | Version the contract or provide a tested migration path. |
| Failure before stream headers | Use the documented HTTP problem contract. |
| Failure after streaming begins | Finish through typed SSE error and terminal events. |
| Retryable side effect | Define idempotency key scope, storage, expiry, and conflict behavior. |
| Volatile upstream boundary | Introduce one consumer-owned port and adapter. |

## Execution Steps

1. Map endpoint, middleware, contracts, callers, and upstream dependencies with CodeGraph.
2. Record current status, payload, side effects, timeout, cancellation, and authorization behavior.
3. Implement the smallest vertical change while preserving compatibility or explicitly versioning it.
4. Test validation boundaries, authorization, rate limits, retry/idempotency, disconnects, timeouts, and both SSE failure phases.
5. Run Ruff, focused pytest and integration tests, plus generated-contract drift checks when schemas change.
6. Inspect the diff for hidden compatibility changes and unjustified layers.

## Output Contract

Return affected endpoints and contracts, compatibility disposition, validation/auth/rate-limit behavior, timeout/cancellation/idempotency evidence, tests run, remaining risks, and rollback boundary.

## References

- `../../../backend/README.md`
- `../../../contracts/chat/v1/README.md`
- `../../../docs/architecture/platform-topology.md`
- `../../../docs/architecture/ai-chat-boundary.md`
- `../pragmatic-clean-architecture/SKILL.md`
- `../delivery-checkpoint/SKILL.md`
