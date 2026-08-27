# HTTP integration sources

## Source configuration

Each source defines:

- HTTPS base URL;
- allowed destination hosts;
- authentication scheme and encrypted credential payload;
- request timeout and response-size limits;
- enabled/disabled state.

Create and test sources from the administration panel. Environment variables are reserved for platform bootstrap and provider infrastructure, not individual business APIs.

## Tool configuration

Each HTTP tool defines a source, relative path, method (`GET`, `POST`, `PUT`, `PATCH`, or `DELETE`), parameter location, JSON input schema, enabled channels, risk level, confirmation requirement, and idempotency behavior.

Use read-only tools by default. A write-capable tool must have a business-defined confirmation flow and an idempotency key strategy before it is enabled for a public channel.

## Response handling

The adapter accepts bounded JSON or file results. It treats transport errors separately from business responses, never follows redirects, and does not return raw credentials or internal headers to the model.
