# CRM-first production release — 2026-09-07

The CRM refactor is deployed at [panel.saltacode.com.ar](https://panel.saltacode.com.ar/)
under explicit owner authorization for production iteration. Existing administrator credentials
remain valid. No external-channel or commercial automation activation was included.

## Released unit

| Item | Evidence |
|---|---|
| Source commit | `16120c966112` |
| Immutable release | `git-16120c966112-20260907T181036Z` |
| API / panel origins | `127.0.0.1:28082` / `127.0.0.1:23000` |
| Schema | `f13d7b9e1f45` → `f14e8c0f2a56` |
| Application processes | API, panel, channel-inbound compatibility worker, outbound worker, web-execution worker, follow-up worker |

The actual API/panel image IDs and all four worker image IDs match the immutable receipt:
`/var/lib/saltacode-agent-platform/receipts/git-16120c966112-20260907T181036Z.receipt`.
The canonical production environment's `APP_VERSION` was updated atomically; other values,
secret material, ownership, permissions, and port bindings were preserved.

Landing, BFF, PostgreSQL, and Redis container/image IDs are unchanged. Independent verification
also confirmed 39 other baseline containers remained running with their original identities.
No DNS, Tunnel, global Docker configuration, or unrelated project was changed. No Git push occurred.

## Data protection

Protected recovery material and verification logs are under:
`/var/lib/saltacode-agent-platform/backups/20260907T181036Z-pre-crm-refactor`.

- PostgreSQL custom-format dump, documents, prior environment/Compose/receipt, and encryption
  keys were copied with directory mode `0700` and file mode `0600`.
- The real dump was restored to disposable PostgreSQL with `--network none`. Current source
  and migrations, using the prior runtime's unchanged dependency set, successfully upgraded
  that restored database and passed Alembic drift checking before the production cutover.
- All 168 pre-existing web messages were compared in memory and remain unchanged. Original
  conversation IDs, agent configuration, administrator password, and persisted provider/channel
  credentials were preserved. Secret values and secret-derived fingerprints were not reported.
- Four clearly marked synthetic acceptance conversations added eight messages. All four were
  closed through authorized, version-checked control transitions; no history was deleted.
  Final acceptance totals were 37 conversations and 176 web messages.
- The disposable restored database and its own anonymous volume were removed after comparison.

This is a verified **same-host** recovery copy, not off-host disaster recovery. The additive
migration performs no backfill. Rollback to the old f13 receipt is blocked by the exact-schema
contract; use a forward fix or a separately reviewed compatibility procedure, never restore
an old database over new conversations.

## Acceptance evidence

| Check | Result |
|---|---|
| Exact-commit `pnpm verify` | Passed: BFF 97 tests, API 420 unit and 148 PostgreSQL tests, panel 91 E2E tests; remaining repository gates passed |
| Production release verification | Receipt, schema, readiness, loopback probes, actual images and worker health passed |
| Real administrator login | Existing credentials accepted through the public panel |
| CRM UI | Inbox, agents, channels and pipeline passed at desktop 1440px and mobile 390px; no horizontal overflow, JavaScript errors, or HTTP failures |
| Authorized CRM reads | Seven real collections returned paginated results with owner/capability metadata |
| Public web chat | Hero submission, actual provider response, close/reopen, reload persistence and scoped Inbox detail passed |
| Test cleanup | Four synthetic threads closed with audit preserved; no additional empty replacement sessions |
| Public site safety | All 11 routes, canonicals/H1, sitemap, robots, contact links, real 404, redirects, security headers and rejected state-neutral chat-contract canary passed |

The acceptance harness was corrected to use browser Fetch's status property, the actual resume
button's accessible name, the nested Inbox conversation control version, and the visible privacy
notice before interacting with the floating launcher. Earlier harness attempts explain the extra
synthetic threads; they were not used to claim successful completion before cleanup passed.
An unacknowledged privacy notice can cover the floating launcher; that existing landing UX is a
separate follow-up, not a landing change in this release.

Evidence files include `repository-quality.log`, `rehearsal-migration.log`,
`final-platform-verify.log`, `container-verification.txt`, `public-verification.txt`,
`crm-panel-acceptance.json`, `chat-production-acceptance.json`, and `data-preservation.json`.
Production screenshots and any sensitive recovery material remain outside Git.

## Activation boundary

The release does not create agents, handoff routes, providers or commercial policies on the
owner's behalf. The progression table remains empty: until configured in Pipeline, quote-contact
capture preserves the previous explicit-handoff requirement.

WhatsApp commercial contact/consent capture, autonomous follow-up planning, and external
quote/calendar/email/Meta integrations remain separate implementation and activation work.
See the [refactor verification and limitations](crm-refactor-2026-09-07.md).
No ranking, Search Console coverage, field Core Web Vitals, physical-device or screen-reader
claim follows from this release. Local ShellCheck remains unavailable.
