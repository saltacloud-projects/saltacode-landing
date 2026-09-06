import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";
const ADMIN_ID = "10000000-0000-0000-0000-000000000001";
const OPPORTUNITY_ID = "20000000-0000-0000-0000-000000000001";
const TASK_ID = "30000000-0000-0000-0000-000000000001";

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

interface FollowUpState {
  status: string;
  version: number;
  conflictNext: boolean;
}

interface RecordedCommand {
  path: string;
  body: Record<string, unknown>;
  idempotencyKey?: string;
  correlationId?: string;
}

function queueItem(state: FollowUpState) {
  return {
    id: TASK_ID,
    opportunity_id: OPPORTUNITY_ID,
    assigned_agent_id: AGENT_ID,
    assigned_operator_id: ADMIN_ID,
    kind: "commercial_follow_up",
    status: state.status,
    state_version: state.version,
    due_at: "2026-09-08T13:00:00Z",
    available_at: "2026-09-08T13:00:00Z",
    attempts: 1,
    max_attempts: 3,
    is_leased: true,
    outbound_status: "delivery_unknown",
    safe_code: "provider_result_uncertain",
    review_required_at: state.status === "review_required" ? "2026-09-08T13:05:00Z" : null,
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-08T13:05:00Z",
  };
}

function detail(state: FollowUpState) {
  return {
    ...queueItem(state),
    conversation_id: null,
    has_retained_source_conversation: true,
    quote_version_id: null,
    scheduled_control_version: 2,
    scheduled_automation_version: 3,
    scheduled_policy_version: 4,
    executed_policy_version: 4,
    has_consent_evidence: true,
    has_executed_consent_evidence: true,
    has_chat_message_evidence: true,
    has_outbound_message_evidence: true,
    completed_at: null,
    cancelled_at: state.status === "cancelled" ? "2026-09-08T13:10:00Z" : null,
    note: "FORBIDDEN_PRIVATE_NOTE",
    contact_point_id: "FORBIDDEN_CONTACT_POINT",
    consent_record_id: "FORBIDDEN_CONSENT",
    correlation_id: "FORBIDDEN_CORRELATION",
    provider_payload: "FORBIDDEN_PROVIDER_PAYLOAD",
  };
}

function events(state: FollowUpState) {
  return {
    items: [
      {
        id: "40000000-0000-0000-0000-000000000001",
        event_type: "review_required",
        from_status: "in_progress",
        to_status: state.status,
        state_version: state.version,
        actor_type: "worker",
        has_actor_agent: false,
        has_actor_admin: false,
        has_actor_worker: true,
        routing_agent_id: AGENT_ID,
        automation_agent_id: AGENT_ID,
        target_channel: "whatsapp",
        control_version: 2,
        automation_version: 3,
        scheduled_policy_version: 4,
        executed_policy_version: 4,
        has_consent_evidence: true,
        has_executed_consent_evidence: true,
        has_causal_consent_evidence: true,
        has_chat_message_evidence: true,
        has_outbound_message_evidence: true,
        safe_code: "provider_result_uncertain",
        created_at: "2026-09-08T13:05:00Z",
      },
    ],
    total: 1,
    limit: 100,
    offset: 0,
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
  state: FollowUpState,
  commands: RecordedCommand[],
  queries: string[],
  activeAdmin = admin,
) {
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith("/auth/me")) return json(route, activeAdmin);
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith("/follow-ups/") && request.method() === "GET") {
      queries.push(url.search);
      return json(route, { items: [queueItem(state)], total: 1, limit: 100, offset: 0 });
    }
    if (path.endsWith(`/follow-ups/${TASK_ID}`) && request.method() === "GET") {
      return json(route, detail(state));
    }
    if (path.endsWith(`/follow-ups/${TASK_ID}/events`) && request.method() === "GET") {
      return json(route, events(state));
    }
    if (path.includes(`/follow-ups/${TASK_ID}/`) && request.method() === "POST") {
      commands.push({
        path,
        body: request.postDataJSON(),
        idempotencyKey: request.headers()["idempotency-key"],
        correlationId: request.headers()["x-correlation-id"],
      });
      if (state.conflictNext) {
        state.conflictNext = false;
        state.version += 1;
        return json(route, { detail: "follow-up state version changed" }, 409);
      }
      if (path.endsWith("/requeue")) state.status = "scheduled";
      if (path.endsWith("/cancel")) state.status = "cancelled";
      if (path.endsWith("/review-resolution")) {
        state.status = request.postDataJSON().resolution === "cancel" ? "cancelled" : "scheduled";
      }
      state.version += 1;
      return json(route, { id: TASK_ID, status: state.status, state_version: state.version });
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

test("operator reads a privacy-minimized queue and cancels only scheduled work", async ({ page }) => {
  await prepare(page);
  const state: FollowUpState = { status: "scheduled", version: 2, conflictNext: false };
  const commands: RecordedCommand[] = [];
  const queries: string[] = [];
  await registerMocks(page, state, commands, queries);

  await page.goto(`/agents/${AGENT_ID}/follow-ups`);
  await expect(page.getByRole("heading", { name: "Seguimientos de Agente comercial" })).toBeVisible();
  await page.getByRole("button", { name: /Seguimiento 30000000/ }).click();
  await expect(page.getByText("Intentos 1/3", { exact: false })).toBeVisible();
  await expect(page.getByText("Lease de worker")).toBeVisible();
  await expect(page.getByText("provider_result_uncertain").first()).toBeVisible();
  for (const forbidden of [
    "FORBIDDEN_PRIVATE_NOTE",
    "FORBIDDEN_CONTACT_POINT",
    "FORBIDDEN_CONSENT",
    "FORBIDDEN_CORRELATION",
    "FORBIDDEN_PROVIDER_PAYLOAD",
  ]) {
    await expect(page.getByText(forbidden)).toHaveCount(0);
  }

  await page.getByRole("button", { name: "Cancelar seguimiento" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].body).toEqual({ expected_version: 2 });
  expect(commands[0].idempotencyKey).toMatch(/^follow-up-cancel-/);
  expect(commands[0].correlationId).toBe(`panel-${commands[0].idempotencyKey}`);
  await expect(
    page
      .getByRole("region", { name: "Detalle de seguimiento" })
      .locator("header")
      .getByText("Cancelado", { exact: true }),
  ).toBeVisible();

  await page.getByLabel("Estado").selectOption("review_required");
  await page.getByLabel("Tipo").selectOption("proposal_reminder");
  await expect.poll(() => queries.some((query) => query.includes("status=review_required"))).toBe(true);
  await expect.poll(() => queries.some((query) => query.includes("kind=proposal_reminder"))).toBe(true);
});

test("authorized reviewer can requeue or resolve review without generic transitions", async ({
  page,
}) => {
  await prepare(page);
  const state: FollowUpState = { status: "review_required", version: 5, conflictNext: false };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands, []);

  await page.goto(`/agents/${AGENT_ID}/follow-ups`);
  await page.getByRole("button", { name: /Seguimiento 30000000/ }).click();
  await page.getByRole("button", { name: "Reencolar después de revisar" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].path).toMatch(/\/requeue$/);
  expect(commands[0].body).toEqual({ expected_version: 5 });
  await expect(
    page
      .getByRole("region", { name: "Detalle de seguimiento" })
      .locator("header")
      .getByText("Programado", { exact: true }),
  ).toBeVisible();

  state.status = "review_required";
  state.version = 7;
  await page.getByRole("button", { name: "Actualizar" }).click();
  await page.getByRole("button", { name: /Seguimiento 30000000/ }).click();
  await page.getByRole("button", { name: "Resolver revisión cancelando" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].path).toMatch(/\/review-resolution$/);
  expect(commands[1].body).toEqual({ expected_version: 7, resolution: "cancel" });

  await expect(page.getByText("transición", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /in.progress|completed/i })).toHaveCount(0);
});

test("review requires its explicit permission and stale commands reload safely", async ({ page }) => {
  await prepare(page);
  const state: FollowUpState = { status: "review_required", version: 3, conflictNext: true };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands, [], {
    ...admin,
    permissions: ["profiles.read", "follow_ups.read", "follow_ups.manage"],
  });

  await page.goto(`/agents/${AGENT_ID}/follow-ups`);
  await page.getByRole("button", { name: /Seguimiento 30000000/ }).click();
  await expect(page.getByText("Tu rol puede observarlo", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reencolar después de revisar" })).toHaveCount(0);
  expect(commands).toHaveLength(0);

  await page.unrouteAll({ behavior: "wait" });
  await registerMocks(page, state, commands, []);
  await page.reload();
  await page.getByRole("button", { name: /Seguimiento 30000000/ }).click();
  await page.getByRole("button", { name: "Reencolar después de revisar" }).click();
  await expect(page.getByRole("alert")).toContainText("El seguimiento cambió");
  await expect(
    page
      .getByRole("region", { name: "Detalle de seguimiento" })
      .getByText("Estado", { exact: true })
      .locator("..")
      .getByText("v4", { exact: true }),
  ).toBeVisible();
});

test("mobile follow-up detail keeps the queue navigable without horizontal overflow", async ({
  page,
}) => {
  await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const state: FollowUpState = { status: "in_progress", version: 4, conflictNext: false };
  await registerMocks(page, state, [], []);

  await page.goto(`/agents/${AGENT_ID}/follow-ups`);
  await page.getByRole("button", { name: /Seguimiento 30000000/ }).click();
  await expect(page.getByRole("button", { name: "Volver a seguimientos" })).toBeVisible();
  await expect(page.getByText("Este estado no admite acciones manuales", { exact: false })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
