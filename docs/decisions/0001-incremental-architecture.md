# 0001: Evolve architecture incrementally

- **Status:** Accepted
- **Date:** 2026-08-30
- **Owners:** Repository maintainers
- **Supersedes:** None
- **Superseded by:** None

## Decision

Apply Clean Architecture as a direction for dependency and trust boundaries, not as a requirement to create speculative layers. Start with the simplest cohesive implementation, preserve the existing static frontend, BFF, and private agent boundaries, and add abstractions or services only when current evidence justifies their cost.

## Context

SaltaCode spans an indexable Astro site, a public FastAPI BFF, and a private agent platform. These boundaries solve distinct trust, deployment, and persistence concerns. Adding generic repositories, factories, buses, microservices, or orchestration before a second concrete use or measurable constraint would increase maintenance without improving the current system.

The intended runtime boundary is documented in [Platform topology](../architecture/platform-topology.md), and the implemented technology choices are documented in [Technology direction](../architecture/technology-direction.md).

## Consequences

- Each change begins as the smallest reversible work unit that preserves public contracts and dependency direction.
- A new layer, service, framework, queue, or shared abstraction needs evidence: duplicated behavior, a volatile dependency, an independent security or release boundary, a measured bottleneck, or a clear testing seam.
- Clean Code simplification comes before architectural extraction; an abstraction must reduce verified coupling rather than rename it.
- Some duplication can remain temporarily when it is cheaper and safer than a premature shared abstraction.
- Architecture can evolve without rewriting stable, validated boundaries.

## Review trigger

Review this decision when measured scale, team ownership, compliance, security isolation, availability, or independent deployment requirements can no longer be met by the existing boundaries.
