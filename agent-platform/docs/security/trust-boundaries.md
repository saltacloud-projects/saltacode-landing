# Trust boundaries

## Browser and BFF

The public browser talks to its application BFF. The BFF validates origin,
rate-limits requests, owns a signed HttpOnly session, records consent, and
authenticates to the private web-chat v2 API. No internal token or provider
credential is sent to the browser.

Web chat v2 is a private BFF contract and does not share the durable external-channel inbox. The BFF remains intentionally small: it does not aggregate Agent Platform resources, choose an acting agent, or own commercial state.

## Human and acting-agent fences

Every conversation persists two independent epochs. `control_version` changes when a human takes or releases control; `automation_version` changes when the acting agent is reassigned. Accepted web work, external-channel work, tool effects, outbound intent and dispatch, follow-ups, and meetings revalidate the relevant snapshots. A stale operation fails closed instead of acting after takeover or reassignment, and one controlled conversation does not pause other conversations.

## Tool execution

Tool input and model output are untrusted. Execution is allowed only when all configured policies agree:

- the agent profile enables the tool;
- the tool is enabled and belongs to an enabled source;
- the current channel is allowed;
- the HTTP method and destination match trusted configuration;
- write actions satisfy confirmation and idempotency requirements;
- the target resolves to an allowed public address and remains within response limits.

The HTTP adapter disables redirects and ambient proxy environment settings to prevent allowlist bypass.

## Credentials and logs

Integration credentials are encrypted at rest with the source master key.
Contact points use a separate Fernet key plus an independent lookup HMAC key;
all three are file-mounted and installed mode `0400` for the unprivileged
runtime. Logs and audit metadata must not contain raw authorization headers,
verification tokens, provider keys, session cookies, or full personal
identifiers.

Only services that call external providers join the dedicated egress network.
Durable workers publish no host ports; PostgreSQL, Redis, migration, bootstrap,
tests, and the administration panel do not join that provider-egress boundary.

## External channel ingress

Provider callbacks are untrusted until their channel adapter authenticates the exact request and resolves an active persisted route and connection. The adapter stores only a bounded canonical envelope in the neutral durable inbox. Payloads are encrypted at rest and integrity-checked; immutable ownership snapshots, provider deduplication, per-thread FIFO, leases, and append-only events prevent cross-agent execution and uncontrolled replay.

Only WhatsApp is executable. Catalog support for Instagram Direct, Facebook Messenger, or email is not an authorization to accept provider traffic. Each new adapter requires provider-specific authentication, callback semantics, credentials, tests, and a real canary.

The inbound administration API is agent-scoped and privacy-minimized. Read models omit decrypted content, provider payloads, personal identifiers, and secrets. Requeue, cancel, and acknowledge are semantic, idempotent, version-checked commands; they do not expose arbitrary worker-owned state transitions.

## Outbound and commercial effects

Outbound records snapshot channel route, connection, adapter, acting agent, and control versions before dispatch. Per-conversation FIFO and effect claims prevent later messages from bypassing an uncertain earlier delivery. A provider timeout after a possible effect becomes `delivery_unknown` and requires review; it is never retried blindly.

An operator with `deliveries.review` may resolve that uncertainty exactly once. Confirming delivery requires write-only provider evidence; confirming non-delivery requires an allowlisted reason. The independent resolution version, row lock, deterministic command hash, and idempotency key prevent stale or duplicate decisions. Resolution records retain only a provider-reference hash and safe suffix beyond the authoritative outbound message, and the read model exposes only the masked suffix. Either decision is terminal and never creates another attempt.

Follow-ups revalidate opportunity ownership, control, acting agent, consent, contact, route, and policy under the consent advisory lock before writing outbound intent. Meetings preserve semantic event evidence and leave `calendar_pending` non-operable until a calendar provider contract exists. Quote records do not become authoritative merely because an estimate was generated.

## Retention and evidence

Retention evaluates conversations under lock and must preserve active operational evidence. Terminal follow-ups retain their historical source conversation ID and event history while the live foreign key is detached. Non-terminal or uncertain follow-ups move to review and block conversation deletion. Meeting references detach with preserved meeting/event evidence. Session reset is not an erasure command.

## WhatsApp

The webhook verifies `X-Hub-Signature-256` against the exact request bytes before parsing. WhatsApp-specific access rules remain inside the adapter and do not define platform identity.
