# Inbox: messaging-first workspace and date filters

This iteration borrows familiar messaging navigation from the supplied WhatsApp
reference, not its branding or its unrelated features. Conversations remain part
of the multi-channel CRM, with human control, agent assignment and audit intact.

Status: deployed and verified on 2026-09-07 at
`https://panel.saltacode.com.ar/inbox`.

## Everyday workflow

1. Find a conversation in the compact list using its visible name or visitor ID.
2. Choose active, unread, historical or all conversations. Expand additional
   filters only when narrowing by channel, operator, control mode or dates.
3. Read the selected transcript with day separators, visible authors and times.
   Keep the conversation header and composer available while scrolling messages.
4. Open operational controls when taking ownership, assigning, pausing or resuming
   automation. These actions are not replaced with ambiguous messaging icons.

Desktop keeps list and transcript together; mobile shows one pane at a time with
an explicit back action. The existing visual tokens and highlighted agent/operator
labels remain. No calls, audio recording, groups, favorites, fake online presence
or unverified delivery/read checkmarks are introduced.

## Filter semantics

| Filter | Meaning |
|---|---|
| Active | Neither status nor control mode is closed; paused and human-controlled conversations remain active. |
| Unread | Active conversations containing visitor messages not acknowledged by this operator. |
| History | Explicitly closed conversations, not merely inactive visitors. |
| All | Both active and historical conversations within the operator's authorized scope. |
| Search | Case-insensitive literal matching of the visible conversation label: display name or `Visitante` plus the principal's short identifier. Maximum 120 characters; no full-transcript or encrypted-contact search. |
| Last message date | Date of the latest stored message, not creation, assignment, read acknowledgement or another administrative update. Empty conversations do not match a date range. |

Calendar ranges use the browser's local timezone, displayed with the controls.
Both selected dates are inclusive in the UI. The request converts local midnight
on the first date to an inclusive instant and local midnight after the last date
to an exclusive instant. The next day is computed by calendar arithmetic, not by
adding 24 hours; daylight-saving transitions must retain the intended dates.

Today covers the current local calendar day. Seven and thirty days include today
and the preceding six or twenty-nine dates. Custom ranges may not be inverted.
Incomplete custom edits must not send an invalid query or silently masquerade as
an applied filter.

All list filters run in PostgreSQL before counting and pagination, in both global
CRM and agent-scoped routes. Changing filters resets the list offset. The sidebar
badge continues to count all authorized unread active conversations, independent
of the visible list's date, search or channel filters.

## API contract

The existing list endpoints accept these additive parameters:

- `last_message_from`: inclusive, timezone-aware timestamp.
- `last_message_before`: exclusive, timezone-aware timestamp.
- `unread_only`: boolean, default false, evaluated for the authenticated operator.
- `search`: optional bounded literal query against the visible label.

Naive timestamps and inverted or empty instant ranges return 422. Existing
`updated_after` and `updated_before` retain their legacy semantics for older callers;
they are not silently redefined to mean the new calendar filter.

Authorized list summaries gain nullable `last_message_at`, a normalized
`last_message_preview` bounded to 140 characters, and `last_message_author_type`.
Latest-message selection has a deterministic timestamp/ID tie-breaker. Authorship
comes from persisted provenance, not current automation ownership. Raw metadata,
staff identities and provider secrets are not part of this preview contract.

## Preserved guarantees and limits

- Live SSE updates do not steal focus, replace drafts or force a reader to the end
  of the transcript. Losing a filter match must not silently close the selected chat.
- Read acknowledgement still applies only to loaded, actually viewed inbound
  message IDs. Filtering, searching and fetching a page do not acknowledge messages.
- Authorization, agent scope and exact unread receipts remain server enforced.
- No database migration, new dependency, public BFF contract or landing change is
  required. Existing 500-message thread loading remains a separate operational limit.
- Latest-message selection and literal search use existing PostgreSQL queries;
  larger histories or operator concurrency require measured query-cost review,
  not an assumption of constant-time search.

## Acceptance checklist

- [x] API: date boundaries, timezone offsets, invalid ranges, empty conversations,
  unread receipts, literal wildcards, authorization and filtering before pagination.
- [x] Panel: presets/custom dates, invalid edits, search, filtered totals and offset reset.
- [x] Live behavior: selection, drafts, focus, unread acknowledgements and reconnection.
- [x] Desktop/mobile: 320 and 390 px, keyboard navigation, visible controls, independent scrolling.
- [x] Exact-source quality gate, release receipt and authenticated production checks.

Local scope gates passed: 496 API unit tests, 165 PostgreSQL integration tests and
110 panel E2E tests, including ten new workspace cases. Browser cases cover daylight
saving days of 23 and 25 hours, midnight without SSE activity, a read thread remaining
open under the unread filter, controls obscuring the transcript without acknowledging
messages, unknown legacy authors and long unbroken content at 320/390/1440 px.
Computed CSS checks distinguish staff and visitor backgrounds; unsupported Tailwind
alpha variants with hexadecimal theme variables were replaced locally with `color-mix`.
This is not a claim of complete screen-reader or physical-device certification.

## Production acceptance

| Boundary | Verified result |
|---|---|
| Source | API commit `5c19914c`; panel and contract commit `d1cf80957b18`. |
| Platform release | `git-d1cf80957b18-20260907T223358Z`; API, panel and four durable workers match receipt image IDs and are healthy. |
| Schema and data | Revision remains `f15f9d1a3b67`; all 193 pre-existing message bodies, authors, timestamps and IDs, and all 38 conversation IDs are preserved. No migration. |
| Other services | All 40 pre-existing containers outside the platform application release are unchanged, including landing, BFF and persistent stores. |
| Authentication and live updates | Unauthenticated Inbox/SSE return 401; authenticated SSE is `no-store`, with snapshot at 0.107 seconds and heartbeat at 16.170 seconds in this sample. |
| Real API filters | Global and agent-scoped canonical routes pass literal search, preview provenance, inclusive/exclusive dates, invalid-input 422 and count-before-pagination checks. |
| Served UI | Chromium at 1440 and 320 px, Firefox at 390 px: custom dates, existing synthetic thread, explicit operator authorship, different bubble colors, reachable closed-thread footer, keyboard back and no page overflow or uncaught errors. |
| Public site | Eleven read-only route checks pass; landing/BFF stay on `git-ef53c51c5195-20260907T203713Z`. No DNS, Tunnel, port or indexable-content changes. |

`pnpm verify` passed on the clean exact source candidate before deployment: 496 API
unit tests, 165 PostgreSQL integration tests, 98 BFF tests, 110 panel E2E tests and
33 landing unit tests, plus build, contract, infrastructure and agentic gates.
Local ShellCheck was unavailable; this iteration changes no shell source.

The production browser check reused an already closed synthetic conversation.
It sent no new messages, changed no ownership or opportunities, and performed no
read acknowledgements. The unread production result was zero for the test operator;
non-empty unread cases are covered by local database and browser tests, not by
creating production traffic. Active-composer geometry is covered locally; the
production synthetic thread correctly exposes a closed-history notice instead.

Protected evidence is stored under
`/var/lib/saltacode-agent-platform/backups/20260907T223358Z-pre-inbox-messaging-ux/`:
database backup, exact gate and deploy logs, API/browser acceptance, independent
release verification, history comparison and private screenshots. The immutable
receipt is under `/var/lib/saltacode-agent-platform/receipts/` using the release tag.
Credentials and transcript snapshots remain outside Git. This same-host backup is
not off-host disaster recovery; no new restore rehearsal was performed for this
schema-unchanged iteration.

Rollback boundary: restore the complete platform application release
`git-182153ebbff8-20260907T211626Z` through the receipt-based procedure, without a
database downgrade or a site rollback. Do not mix the new panel with the old API:
the new filters require both components. No Git push was performed.

## Separate follow-up

Acceptance exposed an existing proxy hardening gap: requesting the agent-scoped
Inbox API without its canonical trailing slash returns a 307 pointing at the
internal upstream origin. The panel already uses the canonical slash, and both
supported list paths passed. Track forwarded-host/redirect handling as a separate
infrastructure fix with an external redirect regression test; it is not included
in this messaging UX release.

See the preceding [live Inbox contract](live-inbox-chat-2026-09-07.md) for durable
read receipts and truthful activity semantics.
