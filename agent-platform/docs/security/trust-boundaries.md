# Trust boundaries

## Browser and BFF

The public browser talks to its application BFF. The BFF validates origin, rate limits requests, owns a signed HttpOnly session, records consent, and authenticates to `/internal/v1/executions`. No internal token or provider credential is sent to the browser.

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

Integration credentials are encrypted at rest with the source master key. Logs and audit metadata must not contain raw authorization headers, verification tokens, provider keys, session cookies, or full personal identifiers.

## WhatsApp

The webhook verifies `X-Hub-Signature-256` against the exact request bytes before parsing. WhatsApp-specific access rules remain inside the adapter and do not define platform identity.
