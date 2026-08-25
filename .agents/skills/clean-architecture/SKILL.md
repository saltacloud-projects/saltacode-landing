---
name: clean-architecture
description: "Trigger: clean architecture, boundaries, layering, coupling, ports, adapters, deuda técnica. Enforce inward dependencies incrementally."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0"
---

## Activation Contract

Load this skill for dependency-direction reviews, boundary design, module decomposition, ports and adapters, or architecture debt remediation.

## Hard Rules

- Use CodeGraph before filesystem-wide architecture conclusions.
- Make domain policy independent from Astro, FastAPI, providers, storage, transport, and deployment tooling.
- Keep dependencies pointing from delivery and infrastructure toward application policy, never the reverse.
- Introduce a port only for a real volatile boundary or test seam; do not create empty layers or generic repositories.
- Keep browser-to-BFF, BFF-to-agent, and deployment contracts explicit and versioned.
- Migrate in bounded vertical slices with passing contracts; never perform a big-bang rewrite.

## Decision Gates

| Responsibility | Owning boundary |
|---|---|
| Business rule or invariant | Domain or application policy |
| Use-case sequencing | Application service |
| HTTP, SSE, Astro, FastAPI | Delivery adapter |
| Provider, Redis, filesystem, AI model | Infrastructure adapter behind a port |
| Cross-process payload | Versioned contract with boundary validation |

## Execution Steps

1. Map deployable units, entrypoints, calls, and dependencies with CodeGraph.
2. Name the use cases and policies before proposing folders or abstractions.
3. Record violations with dependency evidence and operational impact.
4. Select the smallest vertical slice and define its inward-facing contract.
5. Move policy inward, adapt external edges, and preserve runtime behavior.
6. Verify unit, contract, integration, security, SEO, and performance gates that cross the slice.

## Output Contract

Return the dependency map, confirmed violations, bounded fixes, contracts preserved, validation evidence, remaining risks, and next safe slice.

## References

- `../../../AGENTS.md`
- `../../../docs/architecture/platform-topology.md`
- `../../../docs/architecture/technology-direction.md`
- `../../../docs/architecture/ai-chat-boundary.md`
- `../delivery-checkpoint/SKILL.md`
