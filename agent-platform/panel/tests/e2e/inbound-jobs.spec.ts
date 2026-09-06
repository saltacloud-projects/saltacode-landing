import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";
const ADMIN_ID = "10000000-0000-0000-0000-000000000001";
const JOB_ID = "30000000-0000-0000-0000-000000000001";

const admin = {
  id: ADMIN_ID,
  email: "operator@example.test",
  name: "Operator",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["*"],
};

const profile = {
  id: AGENT_ID,
  name: "Agente comercial",
  slug: "commercial",
  version: 1,
  is_active: true,
  is_public: true,
  retention_days: 30,
  description: "Commercial agent",
  prompt_identity: "Identity",
  prompt_domain: "Domain",
  prompt_guardrails: "Guardrails",
  unauthorized_message: "Unauthorized",
  error_message: "Error",
  created_at: "2026-09-06T10:00:00Z",
  updated_at: "2026-09-06T10:00:00Z",
};

interface InboundState {
  status: string;
  phase: string;
  version: number;
  networkFailureNext: boolean;
  conflictNext: boolean;
}

interface RecordedCommand {
  action: string;
  body: Record<string, unknown>;
  idempotencyKey?: string;
  correlationId?: string;
}

function summary(state: InboundState) {
  return {
    id: JOB_ID,
    channel: "whatsapp",
    adapter_key: "FORBIDDEN_ADAPTER",
    adapter_version: 2,
    channel_route_id: "FORBIDDEN_ROUTE_ID",
    channel_route_version: 3,
    channel_connection_id: "FORBIDDEN_CONNECTION_ID",
    channel_connection_version: 4,
    status: state.status,
    phase: state.phase,
    state_version: state.version,
    attempts: 1,
    safe_code: state.status === "review_required" ? "payload_requires_review" : null,
    conversation_id: "FORBIDDEN_CONVERSATION_ID",
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:05:00Z",
    terminal_at: ["ignored", "cancelled"].includes(state.status)
      ? "2026-09-06T10:06:00Z"
      : null,
  };
}

function detail(state: InboundState) {
  return {
    ...summary(state),
    routing_agent_id: "FORBIDDEN_ROUTING_AGENT_ID",
    conversation_control_version: 7,
    automation_agent_id: "FORBIDDEN_AUTOMATION_AGENT_ID",
    conversation_automation_version: 8,
    legacy_payload_quarantined: state.phase === "legacy_quarantined",
    payload: "FORBIDDEN_PAYLOAD",
    contact: "FORBIDDEN_CONTACT",
    provider_message_id: "FORBIDDEN_PROVIDER_ID",
  };
}

function timeline(state: InboundState) {
  return {
    items: [
      {
        id: "40000000-0000-0000-0000-000000000001",
        event_type: "review_required",
        from_status: "failed",
        to_status: state.status,
        state_version: state.version,
        phase: state.phase,
        actor_type: "worker",
        has_actor_admin: false,
        safe_code: "payload_requires_review",
        created_at: "2026-09-06T10:05:00Z",
        correlation_id: "FORBIDDEN_CORRELATION",
        provider_payload: "FORBIDDEN_PROVIDER_PAYLOAD",
      },
    ],
  };
}

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function prepare(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "tokens",
      JSON.stringify({ access_token: "test", refresh_token: "test" }),
    );
  });
}

async function registerMocks(
  page: Page,
  state: InboundState,
  commands: RecordedCommand[],
  queries: string[] = [],
  activeAdmin = admin,
) {
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith("/auth/me")) return json(route, activeAdmin);
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith("/inbound-jobs/") && request.method() === "GET") {
      queries.push(url.search);
      return json(route, { items: [summary(state)], total: 1, limit: 100, offset: 0 });
    }
    if (path.endsWith(`/inbound-jobs/${JOB_ID}`) && request.method() === "GET") {
      return json(route, detail(state));
    }
    if (path.endsWith(`/inbound-jobs/${JOB_ID}/timeline`) && request.method() === "GET") {
      return json(route, timeline(state));
    }
    if (path.includes(`/inbound-jobs/${JOB_ID}/`) && request.method() === "POST") {
      const action = path.split("/").at(-1) ?? "";
      commands.push({
        action,
        body: request.postDataJSON(),
        idempotencyKey: request.headers()["idempotency-key"],
        correlationId: request.headers()["x-correlation-id"],
      });
      if (state.networkFailureNext) {
        state.networkFailureNext = false;
        return route.abort("failed");
      }
      if (state.conflictNext) {
        state.conflictNext = false;
        state.version += 1;
        return json(route, { detail: "inbound state version conflict" }, 409);
      }
      if (action === "requeue") {
        state.status = "queued";
        state.phase = "accepted";
      } else if (action === "cancel") {
        state.status = "cancelled";
        state.phase = "terminal";
      } else if (action === "acknowledge") {
        state.status = "ignored";
        state.phase = "terminal";
      }
      state.version += 1;
      return json(route, {
        id: JOB_ID,
        status: state.status,
        phase: state.phase,
        state_version: state.version,
        safe_code: action,
      });
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

test("reviewer sees minimized ingress evidence and uses only semantic resolutions", async ({
  page,
}) => {
  await prepare(page);
  const state: InboundState = {
    status: "review_required",
    phase: "accepted",
    version: 2,
    networkFailureNext: false,
    conflictNext: false,
  };
  const commands: RecordedCommand[] = [];
  const queries: string[] = [];
  await registerMocks(page, state, commands, queries);

  await page.goto(`/agents/${AGENT_ID}/inbound-jobs`);
  await expect(page.getByRole("heading", { name: "Ingresos externos de Agente comercial" })).toBeVisible();
  await page.getByRole("button", { name: /Ingreso 30000000/ }).click();
  await expect(page.getByRole("button", { name: "Reencolar ingreso" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar ingreso" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reconocer y descartar" })).toBeVisible();
  for (const forbidden of [
    "FORBIDDEN_ADAPTER",
    "FORBIDDEN_ROUTE_ID",
    "FORBIDDEN_CONNECTION_ID",
    "FORBIDDEN_CONVERSATION_ID",
    "FORBIDDEN_ROUTING_AGENT_ID",
    "FORBIDDEN_AUTOMATION_AGENT_ID",
    "FORBIDDEN_PAYLOAD",
    "FORBIDDEN_CONTACT",
    "FORBIDDEN_PROVIDER_ID",
    "FORBIDDEN_CORRELATION",
    "FORBIDDEN_PROVIDER_PAYLOAD",
  ]) {
    await expect(page.getByText(forbidden)).toHaveCount(0);
  }

  await page.getByRole("button", { name: "Reconocer y descartar" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0]).toMatchObject({ action: "acknowledge", body: { expected_version: 2 } });
  expect(commands[0].idempotencyKey).toMatch(/^inbound-acknowledge-/);
  expect(commands[0].correlationId).toBe(`panel-${commands[0].idempotencyKey}`);
  await expect(
    page
      .getByRole("region", { name: "Detalle de ingreso externo" })
      .locator("header")
      .getByText("Reconocido y descartado", { exact: true }),
  ).toBeVisible();

  await page.getByLabel("Estado").selectOption("review_required");
  await expect.poll(() => queries.some((query) => query.includes("status=review_required"))).toBe(true);
});

test("network retry preserves one intent and double submit is blocked", async ({ page }) => {
  await prepare(page);
  const state: InboundState = {
    status: "review_required",
    phase: "claimed",
    version: 5,
    networkFailureNext: true,
    conflictNext: false,
  };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands);

  await page.goto(`/agents/${AGENT_ID}/inbound-jobs`);
  await page.getByRole("button", { name: /Ingreso 30000000/ }).click();
  await page.getByRole("button", { name: "Reencolar ingreso" }).evaluate((button) => {
    button.click();
    button.click();
  });
  await expect.poll(() => commands.length).toBe(1);
  await expect(page.getByRole("alert")).toContainText("conservaremos su clave");

  await page.getByRole("button", { name: "Reencolar ingreso" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].body).toEqual({ expected_version: 5 });
  expect(commands[1].idempotencyKey).toBe(commands[0].idempotencyKey);
  expect(commands[1].correlationId).toBe(commands[0].correlationId);
});

test("stale cancellation reloads the current CAS version", async ({ page }) => {
  await prepare(page);
  const state: InboundState = {
    status: "queued",
    phase: "accepted",
    version: 3,
    networkFailureNext: false,
    conflictNext: true,
  };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands);

  await page.goto(`/agents/${AGENT_ID}/inbound-jobs`);
  await page.getByRole("button", { name: /Ingreso 30000000/ }).click();
  await expect(page.getByRole("button", { name: "Reencolar ingreso" })).toHaveCount(0);
  await page.getByRole("button", { name: "Cancelar ingreso" }).click();
  await expect(page.getByRole("alert")).toContainText("El ingreso cambió");
  await expect(
    page
      .getByRole("region", { name: "Detalle de ingreso externo" })
      .getByText("Estado", { exact: true })
      .locator("..")
      .getByText("v4", { exact: true }),
  ).toBeVisible();
  expect(commands[0].body).toEqual({ expected_version: 3 });
});

test("requeue stays unavailable after the API-declared safe phases", async ({ page }) => {
  await prepare(page);
  const state: InboundState = {
    status: "review_required",
    phase: "replied",
    version: 4,
    networkFailureNext: false,
    conflictNext: false,
  };
  await registerMocks(page, state, []);

  await page.goto(`/agents/${AGENT_ID}/inbound-jobs`);
  await page.getByRole("button", { name: /Ingreso 30000000/ }).click();
  await expect(page.getByRole("button", { name: "Reencolar ingreso" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancelar ingreso" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reconocer y descartar" })).toBeVisible();
});

test("mobile read-only review hides actions and does not overflow", async ({ page }) => {
  await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const state: InboundState = {
    status: "review_required",
    phase: "replied",
    version: 4,
    networkFailureNext: false,
    conflictNext: false,
  };
  await registerMocks(page, state, [], [], {
    ...admin,
    permissions: ["profiles.read", "inbound.read"],
  });

  await page.goto(`/agents/${AGENT_ID}/inbound-jobs`);
  await page.getByRole("button", { name: /Ingreso 30000000/ }).click();
  await expect(page.getByRole("button", { name: "Volver a ingresos externos" })).toBeVisible();
  await expect(page.getByText("Tu rol permite revisar", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reencolar ingreso" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Cancelar ingreso" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reconocer y descartar" })).toHaveCount(0);
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
