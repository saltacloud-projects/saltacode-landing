# Live Inbox and public chat — 2026-09-07

## Functional contract

- **Active** means neither conversation status nor control mode is `closed`. Human-owned
  and paused conversations remain active. It does not mean the visitor is online and
  there is no automatic inactivity closure.
- **History** contains explicitly closed conversations. Existing authenticated agent
  grants scope filters, counts, pagination, thread reads and live notifications.
- The sidebar badge counts **active conversations with unread visitor messages for the
  signed-in operator**, not total messages or waiting LLM executions.
- Read receipts are explicit `(admin, inbound message)` records. Merely listing,
  polling or opening a hidden browser tab does not mark anything read. The panel
  acknowledges loaded inbound IDs when the thread bottom is visible and the page is
  visible; concurrent/unloaded messages are not swept into a timestamp watermark.
- Existing messages start unread because there is no historical evidence of viewing.
  Viewing history can acknowledge it, but closed conversations do not affect the badge.
- Existing thread history is bounded to 500 messages. Unloaded older messages remain
  unread; add older-page navigation before operating threads beyond that bound rather
  than claiming those messages were viewed.

## Live transport

`GET /api/admin/crm/inbox/live` uses authenticated fetch SSE. Tokens never appear in
query strings. `inbox.snapshot` contains only a revision and authorized unread,
active and historical conversation counts. The API checks scoped database metadata
approximately every two seconds and revalidates JWT expiry, account, role and grants
on every cycle. Database sessions close between cycles. Heartbeats are every 15
seconds and streams rotate at 300 seconds; the panel reconnects with bounded backoff.

Replies, read receipts, control/assignment changes and execution state invalidate the
snapshot. The panel refreshes lists and selected threads silently without replacing
composer drafts, focus or the user's position while reading older messages. A failed
connection is shown as reconnecting, not as confirmed live data.

This deliberately uses the existing PostgreSQL state, not a new broker. Work grows
with authorized conversation/message history and connected operators. Move revision
publication to transactional notifications/outbox fanout when measured poll duration,
DB load or operator concurrency warrants it; do not imply constant-time scalability.

## Message authors and activity

- Panel author labels distinguish Visitor, Agent, Operator and System. Agent/operator
  labels use the existing highlighted assignment-note accent.
- Public chat exposes only `author_type` and message timestamps, never operator IDs,
  private agent IDs or staff identities. Agent authorship is based on a persisted
  execution/output link; operator authorship uses stored message provenance. Unknown
  legacy authors remain branded SaltaCode, not inferred from current control mode.
- `history.activity` and ephemeral SSE `chat.activity` are either `null` or
  `{status: "queued" | "running"}`. They do not advance durable message cursors or
  become persisted local typing indicators.
- Running requires a live execution lease, matching control/automation epochs, current
  automation assignment and an open automated conversation. Completed, failed,
  expired, blocked or human-controlled work does not count as typing. The public UI
  says the assistant is preparing a response, not that a human is pressing keys.
- Snapshot expiry is re-evaluated on each server poll. Closing, hiding, losing the
  connection or receiving control changes clears client activity until synchronized.
- Message acceptance means received by the service, not read by a person or delivered
  to an external provider. Public author/time/status layout preserves mobile controls,
  reduced motion, transcript continuity and deferred loading.

## Commercial stall diagnosis

Read-only inspection of the reported visitor showed a completed assistant response
asking qualification questions after the visitor supplied an email. There was no
commercial tool execution, opportunity event or external delivery attempt. The agent
had zero tool bindings, no progression policy and no handoff destination. Generic
persisted prompts/knowledge encouraged qualification but did not activate the native
contact-request tool. This is not a dropped inbound message or an LLM outage.

The bounded correction is an explicit tool binding, guided progression with the
current agent and persisted prompt instructions to offer structured contact/consent
capture on an explicit quote request even when some project details are pending.
Existing free-text contact data is not silently converted into consent or replayed.
A captured request/opportunity is not a generated or delivered quote: the external
quote and email/WhatsApp delivery integrations remain separate activation gates.

## Validation and release boundary

The API adds migration `f15f9d1a3b67` after `f14e8c0f2a56`: receipts only, no transcript
rewrite/backfill. Downgrade refuses to discard populated receipts. Exact-schema
rollback to the prior f14 release is therefore blocked after promotion; use a forward
fix or separately reviewed compatibility operation, not restoration over new chats.

Scope gates and focused browser tests cover authorization revocation, exact reads,
late-commit races, lease expiry, automated/human ownership, reconnection, preserved
drafts/scroll and mobile themes. Release evidence is recorded separately after the
immutable production candidate is deployed. No DNS, Tunnel or public indexable copy
changes are part of this unit. Lazy chat budget adjustment is documented in
[the SEO/performance contract](seo-performance-contract.md); field CWV and rankings
are not inferred from these local checks.
