# 0003: Organize the platform around CRM operations

- **Status:** Accepted
- **Date:** 2026-09-07
- **Owners:** Repository maintainers
- **Supersedes:** None
- **Superseded by:** None

## Decision

Make the platform an operator-centered multichannel CRM. Agents are independently persisted,
configurable execution identities within that platform, not its mandatory global navigation
context. Keep the existing modular application and deployable boundaries.

Daily operations must query the server for authorized records across agents, with optional
filters and bounded pagination. An agent filter is not authorization. Commands continue to
authorize the specific record and its routing/acting ownership before changing anything.

Separate operations, agents, channels, commercial automation, and shared resources/settings
in the panel. Creating an agent must be a complete visible workflow; shared runtime code does
not imply shared prompts, grants, resource bindings, or activation state.

Use guided, typed, persisted commercial policy rather than an arbitrary workflow graph or
prompt-defined permission system. Make continuation versus specialist handoff an explicit
policy choice. Contact/consent capture, opportunity creation, quote issuance, and delivery
are distinct operations, not synonyms for asking the model to write a price.

## Context

The previous UI put every daily task beneath a selected working agent. Its selector only
changed administrative URL context; it neither assigned conversations nor selected the
runtime. Agent creation existed in the API but not in the panel. Commercial contact capture
also unconditionally required a configured handoff to another agent.

The product now needs one operator to manage several specialized agents and channels as one
CRM. Replacing a sidebar label cannot fix missing lifecycle flows or implicit business rules.
Conversely, rewriting persistent history or creating a service per agent would add risk
without solving those user-facing problems.

## Consequences

- Preserve record ownership, audit, human-control epochs, acting-agent epochs, and existing
  scoped commands. Never backfill historical ownership from the currently selected agent.
- Cross-agent read projections enforce permissions and pagination in the database, not by
  fetching every agent into the browser and merging results there.
- Keep database identifiers such as `agent_profiles` compatible when they already represent
  independent agents. A terminology migration is not a reason to rewrite production data.
- Human takeover, consent, tool authorization, idempotency, and uncertain-delivery fencing
  remain non-optional application invariants. Configurable policy cannot disable them.
- The external quote system remains authoritative for issued prices/documents. A model may
  request a permitted tool operation; it cannot manufacture issuance or delivery evidence.
- Channel configuration must distinguish a stored connection from an executable adapter and
  a verified provider activation. Unimplemented providers remain explicitly unavailable.
- No new production release, provider activation, or public BFF contract change is implied by
  this repository refactor.

## Review trigger

Consider a workflow designer only when multiple real workflows cannot be expressed safely
by the guided policies. Consider independent services or organizational tenancy only when
measured isolation, scaling, ownership, or deployment needs justify them. Neither follows
from supporting multiple agents.
