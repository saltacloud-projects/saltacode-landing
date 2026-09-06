import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";
const DELIVERY_ID = "10000000-0000-0000-0000-000000000001";
const CONVERSATION_ID = "20000000-0000-0000-0000-000000000001";
const FULL_PROVIDER_ID = "provider-full-secret-789012";

const reviewer = {
  id: "30000000-0000-0000-0000-000000000001",
  email: "reviewer@example.test",
  name: "Delivery reviewer",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["profiles.read", "deliveries.read", "deliveries.review"],
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

interface DeliveryState {
  status: "delivery_unknown" | "delivered" | "cancelled";
  resolutionVersion: number;
  action: "confirm_delivered" | "confirm_not_delivered" | null;
  evidenceSource: "provider_api" | "provider_console" | null;
  reasonCode:
    | "provider_confirmed_not_delivered"
    | "provider_record_not_found"
    | "operator_verified_not_delivered"
    | null;
  networkFailureNext: boolean;
  serverFailureNext: boolean;
  conflictNext: boolean;
}

interface RecordedCommand {
  body: Record<string, unknown>;
  idempotencyKey?: string;
  correlationId?: string;
}

function delivery(state: DeliveryState) {
  return {
    id: DELIVERY_ID,
    conversation_id: CONVERSATION_ID,
    channel: "whatsapp",
    status: state.status,
    kind: "text",
    sender_type: "automation",
    sequence: 1,
    correlation_id: "correlation-safe-1",
    provider_reference: state.action === "confirm_delivered" ? "…789012" : null,
    attempt_count: 1,
    latest_safe_code: "provider_timeout",
    is_fifo_blocking: state.status === "delivery_unknown",
    blocked_message_count: state.status === "delivery_unknown" ? 2 : 0,
    resolution_version: state.resolutionVersion,
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:01:00Z",
  };
}

function detail(state: DeliveryState) {
  return {
    ...delivery(state),
    channel_route_id: "40000000-0000-0000-0000-000000000001",
    channel_connection_id: "40000000-0000-0000-0000-000000000002",
    adapter_key: "whatsapp-cloud",
    route_version: 1,
    connection_version: 1,
    chat_message_id: null,
    control_version: 0,
    accepted_at: null,
    delivered_at: state.status === "delivered" ? "2026-09-06T10:02:00Z" : null,
    attempts: [
      {
        id: "50000000-0000-0000-0000-000000000001",
        attempt_number: 1,
        control_version: 0,
        created_at: "2026-09-06T10:00:30Z",
      },
    ],
    events: [
      {
        id: "60000000-0000-0000-0000-000000000001",
        attempt_id: "50000000-0000-0000-0000-000000000001",
        event_type: "delivery_unknown",
        from_status: "dispatching",
        to_status: state.status,
        actor_type: "worker",
        safe_code: "provider_timeout",
        created_at: "2026-09-06T10:01:00Z",
      },
    ],
    resolution: state.action
      ? {
          resolution_version: state.resolutionVersion,
          action: state.action,
          provider_reference: state.action === "confirm_delivered" ? "…789012" : null,
          evidence_source: state.evidenceSource,
          reason_code: state.reasonCode,
          has_actor_admin: true,
          created_at: "2026-09-06T10:02:00Z",
        }
      : null,
    provider_message_id: "FORBIDDEN_FULL_PROVIDER_ID",
    provider_payload: "FORBIDDEN_PROVIDER_PAYLOAD",
  };
}

function initialState(): DeliveryState {
  return {
    status: "delivery_unknown",
    resolutionVersion: 0,
    action: null,
    evidenceSource: null,
    reasonCode: null,
    networkFailureNext: false,
    serverFailureNext: false,
    conflictNext: false,
  };
}

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function prepare(
  page: Page,
  state: DeliveryState,
  commands: RecordedCommand[],
  activeUser = reviewer,
) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "tokens",
      JSON.stringify({ access_token: "test", refresh_token: "test" }),
    );
  });
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, activeUser);
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith("/deliveries/") && request.method() === "GET") {
      return json(route, { items: [delivery(state)], total: 1, limit: 100, offset: 0 });
    }
    if (path.endsWith(`/deliveries/${DELIVERY_ID}`) && request.method() === "GET") {
      return json(route, detail(state));
    }
    if (path.endsWith(`/deliveries/${DELIVERY_ID}/resolve`) && request.method() === "POST") {
      const body = request.postDataJSON();
      commands.push({
        body,
        idempotencyKey: request.headers()["idempotency-key"],
        correlationId: request.headers()["x-correlation-id"],
      });
      if (state.networkFailureNext) {
        state.networkFailureNext = false;
        return route.abort("failed");
      }
      if (state.serverFailureNext) {
        state.serverFailureNext = false;
        return json(route, { detail: "temporary provider reconciliation failure" }, 503);
      }
      if (state.conflictNext) {
        state.conflictNext = false;
        state.resolutionVersion += 1;
        return json(route, { detail: "delivery resolution version changed" }, 409);
      }
      state.resolutionVersion += 1;
      state.action = body.action;
      state.evidenceSource = body.evidence_source ?? null;
      state.reasonCode = body.reason_code ?? null;
      state.status = body.action === "confirm_delivered" ? "delivered" : "cancelled";
      return json(route, {
        id: DELIVERY_ID,
        status: state.status,
        resolution_version: state.resolutionVersion,
        action: state.action,
        applied: true,
      });
    }
    return route.fulfill({ status: 500, body: `Mock missing: ${path}` });
  });
}

async function openDelivery(page: Page) {
  await page.goto(`/agents/${AGENT_ID}/deliveries`);
  await page.getByLabel("Lista de entregas").getByRole("button", { name: /whatsapp.*#1/i }).click();
}

test("read-only reviewer sees minimized evidence and no resolution controls", async ({ page }) => {
  const state = initialState();
  await prepare(page, state, [], {
    ...reviewer,
    permissions: ["profiles.read", "deliveries.read"],
  });
  await openDelivery(page);

  const detailPanel = page.getByLabel("Detalle de entrega");
  await expect(detailPanel.getByText("2 entrega(s) en espera")).toBeVisible();
  await expect(detailPanel.getByText("provider_timeout")).toBeVisible();
  await expect(detailPanel.getByText("Tu rol permite revisar", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: /reintentar|reencolar/i })).toHaveCount(0);
  await expect(page.getByText("FORBIDDEN_FULL_PROVIDER_ID")).toHaveCount(0);
  await expect(page.getByText("FORBIDDEN_PROVIDER_PAYLOAD")).toHaveCount(0);
});

test("reviewer irreversibly confirms delivery with write-only provider evidence", async ({
  page,
}) => {
  const state = initialState();
  const commands: RecordedCommand[] = [];
  await prepare(page, state, commands);
  await openDelivery(page);

  await page.getByLabel("ID completo del mensaje en el proveedor").fill(FULL_PROVIDER_ID);
  await page.getByLabel("Fuente de evidencia").selectOption("provider_console");
  await page
    .getByLabel("Confirmo que verifiqué la entrega directamente", { exact: false })
    .check();
  await page.getByRole("button", { name: "Confirmar como entregado" }).click();

  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].body).toEqual({
    action: "confirm_delivered",
    provider_message_id: FULL_PROVIDER_ID,
    evidence_source: "provider_console",
    expected_resolution_version: 0,
  });
  expect(commands[0].idempotencyKey).toMatch(/^delivery-resolution-/);
  expect(commands[0].correlationId).toBe(`panel-${commands[0].idempotencyKey}`);
  await expect(page.getByText("Resolución verificada")).toBeVisible();
  await expect(page.getByText("…789012").first()).toBeVisible();
  await expect(page.getByText("Consola del proveedor")).toBeVisible();
  await expect(page.locator(`input[value="${FULL_PROVIDER_ID}"]`)).toHaveCount(0);
  await expect(page.getByText(FULL_PROVIDER_ID)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /reintentar|reencolar/i })).toHaveCount(0);
});

test("reviewer confirms non-delivery with an allowlisted reason", async ({ page }) => {
  const state = initialState();
  const commands: RecordedCommand[] = [];
  await prepare(page, state, commands);
  await openDelivery(page);

  await page.getByLabel("Evidencia de no entrega").selectOption("provider_record_not_found");
  await page.getByLabel("Confirmo la no entrega", { exact: false }).check();
  await page.getByRole("button", { name: "Confirmar como no entregado" }).click();

  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].body).toEqual({
    action: "confirm_not_delivered",
    reason_code: "provider_record_not_found",
    expected_resolution_version: 0,
  });
  await expect(page.getByText("No entrega confirmada")).toBeVisible();
  await expect(page.getByText("El proveedor no encontró el registro")).toBeVisible();
  await expect(page.getByRole("button", { name: /reintentar|reencolar/i })).toHaveCount(0);
});

test("network retry keeps one idempotency key and blocks double submit", async ({ page }) => {
  const state = initialState();
  state.networkFailureNext = true;
  const commands: RecordedCommand[] = [];
  await prepare(page, state, commands);
  await openDelivery(page);

  await page.getByLabel("ID completo del mensaje en el proveedor").fill(FULL_PROVIDER_ID);
  await page
    .getByLabel("Confirmo que verifiqué la entrega directamente", { exact: false })
    .check();
  await page.getByRole("button", { name: "Confirmar como entregado" }).evaluate((button) => {
    button.click();
    button.click();
  });
  await expect.poll(() => commands.length).toBe(1);
  await expect(page.getByRole("alert")).toContainText("conservaremos su clave");

  await page.getByRole("button", { name: "Confirmar como entregado" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].idempotencyKey).toBe(commands[0].idempotencyKey);
  expect(commands[1].correlationId).toBe(commands[0].correlationId);
});

test("server failure retry keeps the same idempotency key", async ({ page }) => {
  const state = initialState();
  state.serverFailureNext = true;
  const commands: RecordedCommand[] = [];
  await prepare(page, state, commands);
  await openDelivery(page);

  await page.getByLabel("Confirmo la no entrega", { exact: false }).check();
  await page.getByRole("button", { name: "Confirmar como no entregado" }).click();
  await expect(page.getByRole("alert")).toContainText("conservaremos su clave");

  await page.getByRole("button", { name: "Confirmar como no entregado" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].idempotencyKey).toBe(commands[0].idempotencyKey);
  expect(commands[1].correlationId).toBe(commands[0].correlationId);
});

test("stale resolution refreshes its independent CAS version", async ({ page }) => {
  const state = initialState();
  state.conflictNext = true;
  const commands: RecordedCommand[] = [];
  await prepare(page, state, commands);
  await openDelivery(page);

  await page.getByLabel("Confirmo la no entrega", { exact: false }).check();
  await page.getByRole("button", { name: "Confirmar como no entregado" }).click();

  await expect(page.getByRole("alert")).toContainText("La resolución cambió");
  await expect(
    page.getByText("Versión de resolución").locator("..").getByText("1", { exact: true }),
  ).toBeVisible();
  expect(commands[0].body).toMatchObject({ expected_resolution_version: 0 });
});

test("mobile delivery review has no horizontal overflow", async ({ page }) => {
  const state = initialState();
  await prepare(page, state, []);
  await page.setViewportSize({ width: 390, height: 844 });
  await openDelivery(page);

  await expect(page.getByRole("button", { name: "Volver a entregas" })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
