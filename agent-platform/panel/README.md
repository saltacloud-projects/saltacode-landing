# CRM panel development

The panel separates daily CRM operations from agent configuration. See
[`../docs/architecture/administration-model.md`](../docs/architecture/administration-model.md)
for ownership, permissions, channels, and guided commercial policy.

## Local API target

Vite does **not** proxy API calls unless `PANEL_API_TARGET` is explicitly supplied. An earlier
inherited default targeted port 8001, which can belong to another production project on this
host. Never guess a development target from an occupied port.

After starting an isolated, migrated Agent API with disposable data on an unused loopback port:

```bash
PANEL_API_TARGET=http://127.0.0.1:<isolated-api-port> npm run dev -- --host 127.0.0.1
```

The target variable is read by Vite's development server; it is not a browser provider secret.
Production proxy configuration remains owned by the container/release topology. A local build
does not update `panel.saltacode.com.ar` or grant permission to mutate production data.

## Checks

```bash
npm run check
npm run build
npm run test:e2e
```

Playwright's regular suite mocks the administration API and exercises UI contracts. It does
not replace PostgreSQL authorization/migration tests or an authenticated browser acceptance
against an isolated real API. Keep synthetic credentials, browser storage, and review logs
outside version control. Screen-reader and device testing remain separate from automated gates.
