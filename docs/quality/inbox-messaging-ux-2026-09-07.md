# Inbox: messaging-first workspace and date filters

This iteration borrows familiar messaging navigation from the supplied WhatsApp
reference, not its branding or its unrelated features. Conversations remain part
of the multi-channel CRM, with human control, agent assignment and audit intact.

Status: implementation and local acceptance complete; production acceptance pending.

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
- [ ] Exact-source quality gate, release receipt and authenticated production checks.

Local scope gates passed: 496 API unit tests, 165 PostgreSQL integration tests and
110 panel E2E tests, including ten new workspace cases. Browser cases cover daylight
saving days of 23 and 25 hours, midnight without SSE activity, a read thread remaining
open under the unread filter, controls obscuring the transcript without acknowledging
messages, unknown legacy authors and long unbroken content at 320/390/1440 px.
Computed CSS checks distinguish staff and visitor backgrounds; unsupported Tailwind
alpha variants with hexadecimal theme variables were replaced locally with `color-mix`.
This is not a claim of complete screen-reader or physical-device certification.

See the preceding [live Inbox contract](live-inbox-chat-2026-09-07.md) for durable
read receipts and truthful activity semantics.
