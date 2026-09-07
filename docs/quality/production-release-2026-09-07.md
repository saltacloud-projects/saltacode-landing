# Commercial platform production release — 2026-09-07

Agent Platform and the public landing/BFF were promoted independently. Real public chat,
persisted history and human intervention passed acceptance. Commercial contact-to-opportunity
activation remains blocked on owner-defined handoff configuration, not deployment.

## Promoted releases

| Unit | Immutable release | Origin |
|---|---|---|
| Agent API, panel and four durable workers | `git-487f79415035-20260907T045356Z` | API `127.0.0.1:28082`, panel `127.0.0.1:23000` |
| Landing and web BFF | `git-dc3dd9c4b4c0-20260907T050456Z` | Site `127.0.0.1:18080`, BFF `127.0.0.1:18081` |

Public entrypoints remain [the site](https://saltacode.com.ar/) and
[the administration panel](https://panel.saltacode.com.ar/). No DNS, Tunnel, runtime port,
global Docker configuration or unrelated application changes were made.

Release evidence is selected by `/var/lib/saltacode-agent-platform/current-agent-platform-release`
and `/var/lib/saltacode/current-site-receipt`. The latter points to
`20260907T050659Z-site-git-dc3dd9c4b4c0-20260907T050456Z.receipt`.

## Data protection and migration

- Protected PostgreSQL dumps, documents, prior Compose definitions, receipts and host
  configuration/key archives are stored in
  `/var/lib/saltacode-agent-platform/backups/20260907T040202Z-pre-commercial-platform`.
  Directory mode is `0700`; files are `0600`. This is a same-host recovery copy, not an
  independently verified off-host backup.
- The real backup was restored to disposable PostgreSQL on an internal-only Docker network,
  then upgraded from `c6d7e8f9a0b1` to `f13d7b9e1f45`; bootstrap and schema drift checks passed.
- A representative legacy fixture exposed a `NOT NULL` ordering defect in f12. Commit
  `487f7941` fixes the backfill order and regression fixture before production migration.
  Completed, queued, processing and failed legacy records were exercised separately.
- All 152 original messages were compared after deployment and preserved unchanged.
  The original provider credential and administrator password records were also unchanged;
  comparisons stayed in memory without printing or retaining their values.
- New contact encryption and lookup keys are independent, protected and backed up. Existing
  provider/session keys were not rotated.
- Three explicitly marked synthetic acceptance conversations added ten messages. Those
  conversations were closed through audited APIs, not deleted. Final totals: 33 conversations,
  162 messages, including the original 30 conversations.

The f12 table rename is incompatible with the old application. **Do not roll the Agent Platform
back across the schema advance or restore a database over new conversations.** Use a reviewed
forward fix or separately proven compatibility procedure. See the
[platform release contract](../../agent-platform/docs/operations/release-and-rollback.md).

## Verification evidence

| Check | Result |
|---|---|
| Full `pnpm verify` at the final site source commit | Passed |
| BFF | 97 tests passed |
| Agent API | 389 unit and 124 PostgreSQL integration tests passed |
| Panel local E2E | 66 tests passed; these are not a substitute for live acceptance |
| Live panel login and agent inbox | Passed in Chromium at 1440px and 390px; no horizontal overflow or JavaScript runtime errors |
| Real public v2 chat | Provider response, visitor retry deduplication and signed-session history after client reload passed |
| Human intervention | Takeover, inbound persistence without automated reply, idempotent manual reply visible publicly, explicit resume, resumed provider response and stale-version `409` passed |
| Real landing browser flow | Hero submitted once, chat closed/reopened without typing, reload preserved messages; desktop/mobile layout passed |
| Local and public HTTP/SEO safety | All 11 routes, canonicals, sitemap, robots, real 404 behavior, redirects, security headers and state-neutral chat canary passed |
| Runtime | Receipt checks and health checks passed for both release units and all four platform workers |

The fresh-browser flow performs two expected empty-session probes returning `404`:
`/api/v2/chat/history` and `/api/v1/chat/session/upgrade`. The UI handles them and chat works;
they still produce browser network-console noise. The initial acceptance harness classified
them too broadly as failures; the corrected harness allows only these pre-submission probes,
while rejecting unexpected HTTP failures and JavaScript errors. Removing this noise is a
separate contract/UX improvement, not evidence of a broken chat.

No ranking, Search Console coverage, field Core Web Vitals or exhaustive cross-browser
accessibility claim follows from these checks. ShellCheck was unavailable locally; shell
syntax and the repository infrastructure fixtures passed.

## Build-only network exception

The first site build failed before promotion: Docker's default build bridge could not resolve
the npm registry (`EAI_AGAIN`), while host DNS and a host-network build succeeded. The old site
remained healthy. Commit `dc3dd9c4` adds an explicit, validated build-only network override and
records it in the non-secret receipt contract. The final site build used
`SALTACODE_BUILD_NETWORK=host`; runtime network models remained identical. No global daemon
change was made. See the [infrastructure runbook](../../infrastructure/README.md#build-network-override).

## Activation boundary and next step

Production has one active web route, zero active external-channel routes, zero commercial
handoff routes and no enabled commercial automation policies. No WhatsApp, social-channel,
email, quote-provider or automatic follow-up activation was performed.

The contact capture endpoint requires an active `quote_requested` handoff to a distinct,
configured opportunity agent. Without it the operation fails closed without partial contact
persistence. Consequently, production contact/opportunity acceptance was not run: first define
the opportunity agent's name, identity and responsibility with the owner, configure the handoff
and required tool binding, then execute a synthetic consent/contact/opportunity acceptance test.
External delivery and follow-up activation need their own provider and policy gates.
