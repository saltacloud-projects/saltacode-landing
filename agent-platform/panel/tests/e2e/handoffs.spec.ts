import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_A = "00000000-0000-0000-0000-0000000000a1";
const AGENT_B = "00000000-0000-0000-0000-0000000000b2";
const ROUTE_ID = "10000000-0000-0000-0000-000000000001";

const admin = {
  id: "20000000-0000-0000-0000-000000000001",
  email: "operator@example.test",
  name: "Operator",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["profiles.read", "opportunities.manage"],
};

const profiles = [
  {
    id: AGENT_A,
    name: "Agente comercial",
    slug: "commercial",
    version: 1,
    is_active: true,
    is_public: true,
    retention_days: 30,
    description: "Commercial",
    prompt_identity: "Identity",
    prompt_domain: "Domain",
    prompt_guardrails: "Guardrails",
    unauthorized_message: "Unauthorized",
    error_message: "Error",
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:00:00Z",
  },
  {
    id: AGENT_B,
    name: "Agente de oportunidades",
    slug: "opportunities",
    version: 1,
    is_active: true,
    is_public: false,
    retention_days: 30,
    description: "Opportunities",
    prompt_identity: "Identity",
    prompt_domain: "Domain",
    prompt_guardrails: "Guardrails",
    unauthorized_message: "Unauthorized",
    error_message: "Error",
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:00:00Z",
  },
];

interface HandoffState {
  routes: Array<Record<string, unknown>>;
  commands: Array<{ method: string; body: Record<string, unknown> }>;
}

async function json(route: Route, value: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
}

async function prepare(page: Page, state: HandoffState) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "tokens",
      JSON.stringify({ access_token: "test", refresh_token: "test" }),
    );
  });
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/profiles/")) return json(route, profiles);
    if (path.endsWith("/handoff-routes/") && request.method() === "GET") {
      return json(route, state.routes);
    }
    if (path.endsWith("/handoff-routes/") && request.method() === "POST") {
      const body = request.postDataJSON();
      state.commands.push({ method: "POST", body });
      const created = {
        id: "10000000-0000-0000-0000-000000000002",
        source_agent_id: AGENT_A,
        target_agent_id: body.target_agent_id,
        trigger: body.trigger,
        is_active: body.is_active,
        version: 0,
        created_at: "2026-09-06T10:01:00Z",
        updated_at: "2026-09-06T10:01:00Z",
      };
      state.routes.push(created);
      return json(route, created);
    }
    if (path.endsWith(`/handoff-routes/${ROUTE_ID}`) && request.method() === "PATCH") {
      const body = request.postDataJSON();
      state.commands.push({ method: "PATCH", body });
      const current = state.routes[0];
      Object.assign(current, {
        target_agent_id: body.target_agent_id ?? current.target_agent_id,
        is_active: body.is_active ?? current.is_active,
        version: Number(current.version) + 1,
      });
      return json(route, current);
    }
    return route.fulfill({ status: 500, body: `Mock missing: ${request.method()} ${path}` });
  });
}

function existingRoute() {
  return {
    id: ROUTE_ID,
    source_agent_id: AGENT_A,
    target_agent_id: AGENT_B,
    trigger: "quote_requested",
    is_active: true,
    version: 3,
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:00:00Z",
  };
}

test("operator creates and updates an agent-scoped handoff rule", async ({ page }) => {
  const state: HandoffState = { routes: [existingRoute()], commands: [] };
  await prepare(page, state);
  await page.goto(`/agents/${AGENT_A}/handoffs`);

  await expect(page.getByText("la conversación original conserva su agente", { exact: false })).toBeVisible();
  await page.getByLabel("Agente destino").selectOption(AGENT_B);
  await page.getByLabel("Disparador").selectOption("manual_escalation");
  await page.getByRole("button", { name: "Crear regla" }).click();

  await expect.poll(() => state.commands.length).toBe(1);
  expect(state.commands[0]).toMatchObject({
    method: "POST",
    body: {
      target_agent_id: AGENT_B,
      trigger: "manual_escalation",
      is_active: true,
    },
  });
  expect(state.commands[0].body).not.toHaveProperty("source_agent_id");
  expect(state.commands[0].body.idempotency_key).toMatch(/^handoff-create-/);

  const rules = page.getByLabel("Reglas de handoff");
  await rules.getByRole("checkbox", { name: "Activa" }).first().click();
  await expect.poll(() => state.commands.length).toBe(2);
  expect(state.commands[1]).toMatchObject({
    method: "PATCH",
    body: { is_active: false, expected_version: 3 },
  });
  expect(state.commands[1].body.idempotency_key).toMatch(/^handoff-update-/);
});

test("mobile handoff workspace has no horizontal overflow", async ({ page }) => {
  const state: HandoffState = { routes: [existingRoute()], commands: [] };
  await prepare(page, state);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/agents/${AGENT_A}/handoffs`);

  await expect(
    page.getByLabel("Reglas de handoff").getByText("Presupuesto solicitado"),
  ).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
