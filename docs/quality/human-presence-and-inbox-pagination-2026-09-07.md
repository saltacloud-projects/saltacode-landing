# Human typing and Inbox pagination

Status: implementation and local scope gates complete; production acceptance pending.
This document does not activate an external channel.

## Behavior

The existing activity indicator represents a queued or running AI execution. Human
takeover must continue to suppress it. Human typing is an independent, temporary
signal, not a message, read receipt, online status or proof that a reply will arrive.

- The landing displays operator typing only for the current human-controlled chat.
- The CRM displays visitor typing from the existing web conversation.
- Composer activity sends a boolean, never draft contents. No conversation or
  session is created merely because someone starts typing.
- Activity expires after eight seconds without renewal. Send, blur, hide and close
  clear it; disconnection expires it even if a final clear cannot be delivered.
- Per-tab identity and sequence numbers prevent reordered requests from restoring
  older state. Clearing one tab must not erase another tab's current activity.
- Current conversation, route, operator ownership, permissions and control version
  remain authoritative. Old operator signals cannot survive reassignment or resume.
- Presence is bounded and ephemeral in the existing Redis, not persisted as
  transcript or audit events. Redis failure hides presence without breaking chat.

Each actor has at most eight retained browser instances, with 32-second sequence
tombstones and a six-signals-per-second aggregate limit. CRM presence invalidation
reads at most 64 authorized agent indexes and 512 conversation candidates plus a
sentinel. Overflow or an unavailable presence backend explicitly degrades human
indicators, not messages, unread counts, AI activity or operator control. Recovery
requires a fresh snapshot. No unbounded Redis scan or SQL ID list is issued.

## Pagination

The page size is 50. Production inspection returned exactly 30 active conversations,
so `1–30 of 30` was a valid single page, not a frozen counter. Previous/next controls
must be unavailable when there is nowhere to navigate.

A real edge case exists when live updates shrink a multi-page result set: an offset
that was valid may become out of range. The Inbox must recover to a valid page,
without dropping an independently selected conversation or its draft. A single page
should explicitly communicate that all matching conversations are already shown.

## Acceptance gates

- [x] API: bound identities, permissions, ownership epochs, expiry, sequence order,
  bounded per-tab state, multi-tab cleanup and Redis failure.
- [x] BFF: existing session only, same-origin protection, bounded input and a
  separate presence rate limit that does not consume the message budget.
- [x] Clients: real composer activity, inactivity/blur/send/hide cleanup, stale
  snapshot rejection, retained AI suppression and backward-compatible defaults.
- [x] Pagination: more than 50 results, previous/next, filter changes, live shrink,
  empty results and preserved thread/draft.
- [ ] Complete scope gates and served-runtime verification.

Scope gates passed: 530 API unit/contract tests, 174 PostgreSQL integration tests
(including nine using disposable real Redis), 128 BFF tests, 122 panel E2E cases,
and 40 landing unit tests. API/BFF Ruff, panel Biome/build, Astro/build/server,
generated contracts and agentic validation passed. A local Chromium mobile harness
also exercises deferred presence imports after close/reset with mocked transport.
These figures are local evidence, not proof of provider setup or field performance.

Cross-channel history continuity and channel onboarding are separate work units.
Do not remove the current WhatsApp transfer limitation until a verified linking
flow and authorized history access actually exist.
See [channel setup and continuity](../architecture/channel-onboarding-and-continuity.md)
for the verified current limitations and ordered follow-up.

## Release compatibility

Promote the tolerant landing/BFF first, then the Agent API/panel. The older API has
no presence field or endpoint; the new BFF defaults missing snapshots to inactive,
and a missing presence endpoint must not interfere with sending messages.

The old BFF strictly rejects unexpected fields in history/event responses. Therefore
the new API must not be promoted first. Roll back the API before restoring an older
BFF, or retain the tolerant new BFF when reverting only the platform. Independent
release units do not imply arbitrary rollback order across a strict wire contract.
