---
name: security-privacy
description: "Trigger: security, privacy, threat model, auth, secrets, CSP, CORS, CSRF, SSRF, consent, retention. Review controls and evidence safely."
license: Apache-2.0
metadata:
  author: "Oscar Vargas"
  version: "1.0.0"
---

## Activation Contract

Load this skill for threat or privacy reviews, authentication/authorization, trust boundaries, isolation, secrets, browser security, abuse controls, personal data, consent, cookies, retention, or deletion.

## Hard Rules

- Start read-only. Obtain explicit approval before external scanning, active provider tests, account changes, destructive tests, or use of real personal data.
- Map identities, assets, trust boundaries, data flows, tenants, entry points, and privileged operations before judging controls.
- Verify authentication and object-scoped authorization separately; never infer authorization from UI visibility, CORS, or authentication alone.
- Keep secrets server-side, least-privileged, redacted, and rotatable. Treat confirmed exposure as an incident, not a documentation fix.
- Evaluate CSP, CORS, CSRF, SSRF, validation, isolation, rate limits, replay, logging, and failure behavior against the actual request path.
- Minimize personal data. Define purpose, lawful/consent basis, recipients, storage, retention, access, deletion, and backup behavior before collection.
- Separate verified technical behavior, published policy, legal requirement, and legal unknown. Do not present technical review as legal advice.

## Decision Gates

| Evidence | Action |
|---|---|
| Cookie-authenticated state change | Require CSRF protection; CORS alone is insufficient. |
| User-controlled outbound target | Enforce allowlists, DNS/IP checks, redirect policy, timeouts, and bounded responses. |
| Anonymous or costly endpoint | Define identity-aware limits, abuse handling, and fail-open/fail-closed behavior. |
| Personal or chat data | Verify consent where required, minimization, retention, export/access, deletion, and processor disclosure. |
| Legal wording or compliance claim | Mark counsel/owner validation separately from code evidence. |

## Execution Steps

1. Use CodeGraph to trace entry points and trust boundaries; inspect current configuration and tests.
2. Build a compact threat/data-flow table with asset, actor, boundary, abuse case, control, and evidence.
3. Test locally with synthetic data first; request approval before any external or production-facing test.
4. Rank findings by exploitability, impact, affected data, and evidence confidence; propose the smallest reversible control.
5. Run focused validation, preserve secrets in output, save durable findings to Engram, and finish with the delivery checkpoint.

## Output Contract

Return scope, trust/data flows, verified controls, findings with evidence and severity, legal-versus-technical unknowns, validation, remaining risk, and any external test still awaiting approval.

## References

- `../../../docs/architecture/platform-topology.md`
- `../../../docs/architecture/ai-chat-boundary.md`
- `../../../docs/agentic/governance.md`
- `../delivery-checkpoint/SKILL.md`
