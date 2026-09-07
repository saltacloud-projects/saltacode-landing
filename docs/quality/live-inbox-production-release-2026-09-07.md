# Live Inbox and commercial capture: production acceptance

Released on 2026-09-07 with explicit authorization to deploy this iteration. The public
chat and administration Inbox now expose live arrivals, verified response activity and
message authors. A real-provider canary also completed structured contact capture and
opened its resulting opportunity in the panel. No external quote or delivery was sent.

See the [functional contract](live-inbox-chat-2026-09-07.md) for active/history semantics,
per-operator unread receipts, transport, known limits and the commercial stall diagnosis.

## Released artifacts

| Unit | Immutable release | Receipt |
|---|---|---|
| Landing and public BFF | `git-ef53c51c5195-20260907T203713Z` | `/var/lib/saltacode/20260907T203926Z-site-git-ef53c51c5195-20260907T203713Z.receipt` |
| Agent API, panel and four required workers | `git-182153ebbff8-20260907T211626Z` | `/var/lib/saltacode-agent-platform/receipts/git-182153ebbff8-20260907T211626Z.receipt` |

The final API-only fixes do not require another site build. All six platform services
match the final receipt's immutable image IDs and are healthy. Canonical environment
files reference the deployed releases; unrelated values, ownership and modes were
preserved. DNS, Tunnel routing, public ports and unrelated applications were not changed.
Thirty-five unrelated/store container IDs match the pre-release snapshot.

## Acceptance evidence

| Check | Observed result |
|---|---|
| Full repository gate on clean source `182153ebbff8` | PASS: 455 API unit, 160 PostgreSQL integration, 98 BFF, 100 panel E2E and 33 landing unit tests; remaining build, contract, infrastructure and agentic gates passed. |
| Existing operator login and live authorization | PASS; unauthenticated live stream returns 401. |
| Public Inbox SSE through Cloudflare | Initial snapshot 0.197 s, heartbeat 16.174 s, `Cache-Control: no-store`; these timings are one observation, not an SLA. |
| New public message without manual panel refresh | Appeared automatically in the live Inbox canary. |
| Final authorized lifecycle snapshot | 30 active, 8 historical, 38 total, 30 unread active conversations after closing the synthetic thread. Old unread messages were not backfilled as read. |
| Public agent activity and authors | Queued and preparing states observed; visitor, agent and operator labels verified. Human ownership clears agent activity. |
| Reload and mobile continuity | Operator author survives reload; mobile 390 px has no horizontal overflow or JavaScript exceptions in the recorded canary. |
| Actual LLM tool and consent form | Native tool invoked; structured form appeared; quote consent starts unchecked and optional follow-up consent remained unchecked. |
| Contact capture and replay | POST 202; repeating the identical request returned the same opportunity, not a duplicate. |
| Resulting CRM opportunity | Authorized GET 200 and actual panel detail rendered linked web conversation and consent; ownership stayed with the current agent. |
| Synthetic cleanup | Opportunity transitioned to lost and conversation closed through audited versioned endpoints; transcript and audit retained. No quote/follow-up task created. |
| Original persisted history | All 186 pre-release message records remain byte-for-field equivalent in the decoded comparison; all 37 original conversation IDs retained. Final totals: 193 messages, 38 conversations. |
| Public SEO/HTTP regression | All 11 routes passed canonical, heading, robots, sitemap, contact path, security header and actual-404 checks. Rejected chat-contract canary passed separately from the real positive chat test. |

The reported visitor's original messages were not replayed or converted into consent.
The successful commercial capture used only the explicitly synthetic conversation.

## Defects found by the positive canary

Three forward fixes were necessary beyond the initial live Inbox release:

1. Preserve bounded commercial form descriptors in the public event projection.
2. Initialize native and declarative tool catalogs in the worker process that actually
   executes the agent, not just in the API lifespan.
3. Remove a misplaced required follow-up destination field from the linked-conversation
   DTO so that a populated opportunity can be read, not merely created.

Audited persistent configuration now binds the existing native contact-request tool,
offers the structured form for explicit quote requests and uses `keep_agent` progression.
This does not activate a quote provider, outbound delivery or automatic marketing.

## Data safety and rollback

The initial release added receipt-only migration `f15f9d1a3b67` after `f14e8c0f2a56`.
The protected pre-release backup was restored into an isolated, network-disabled
PostgreSQL container and successfully migrated with drift checks and the 186-message
baseline. That rehearsal container and its private anonymous volume were removed.
Additional protected database dumps preceded both forward releases.

Evidence and backups are under
`/var/lib/saltacode-agent-platform/backups/20260907T203457Z-pre-live-inbox`
(directory 0700, files 0600). They include receipts, quality logs, configuration before/after,
public SSE checks, positive browser acceptance and data-preservation results. Browser
storage, screenshots and raw database snapshots are private and must not enter Git.
This same-host backup is not evidence of off-host disaster recovery.

Do not restore the old database over new chats. Automatic application rollback to f14 is
blocked; f15 receipts require their ordinary compatibility checks. Earlier f15 artifacts
would reintroduce the canary defects. The older strict BFF cannot consume the new API
presentation fields, so a site-only rollback across that contract is unsafe; see the
[cross-unit compatibility gate](live-inbox-chat-2026-09-07.md#strict-consumer-rollout-compatibility).

## Remaining boundaries

- Quote generation and actual email/WhatsApp delivery still require their separately
  configured and verified providers. Capturing a request is not sending a quote.
- Existing Inbox history loads at most 500 messages; older unseen records remain unread.
  Add older-page navigation when that operational limit is reached.
- Public initial JavaScript remains 5,803 bytes. Deferred chat is 24,731 bytes JS and
  10,140 bytes CSS, within the reviewed [budgets](seo-performance-contract.md).
  No rankings or field Core Web Vitals improvement is claimed.
- The landing still has no automatic source formatter; style was reviewed against its
  existing conventions. Local ShellCheck was unavailable; shell syntax and existing
  release/infrastructure tests passed.
- No Git push, additional provider activation or unrelated infrastructure change occurred.
