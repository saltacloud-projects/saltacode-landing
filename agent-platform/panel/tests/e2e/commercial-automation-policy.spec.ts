import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";

const profile = {
  id: AGENT_ID,
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
};

interface TestPolicy {
  agent_id: string;
  is_enabled: boolean;
  allowed_kinds: string[];
  timezone: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  min_interval_seconds: number;
  max_attempts: number;
  max_daily_tasks: number;
  max_pending_tasks: number;
  version: number;
}

const defaultPolicy = (): TestPolicy => ({
  agent_id: AGENT_ID,
  is_enabled: false,
  allowed_kinds: [],
  timezone: "UTC",
  quiet_hours_start: null,
  quiet_hours_end: null,
  min_interval_seconds: 3600,
  max_attempts: 3,
  max_daily_tasks: 25,
  max_pending_tasks: 100,
  version: 0,
});

interface PolicyState {
  policy: TestPolicy;
  updates: Array<Record<string, unknown>>;
  conflictOnce?: boolean;
  getStatus?: number;
}

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
}

async function prepare(
  page: Page,
  state: PolicyState,
  permissions = [
    "dashboard.read",
    "profiles.read",
    "opportunities.read",
    "opportunities.manage",
  ],
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
    if (path.endsWith("/auth/me")) {
      return json(route, {
        id: "20000000-0000-0000-0000-000000000001",
        email: "operator@example.test",
        name: "Operator",
        role: "admin",
        is_active: true,
        must_change_password: false,
        permissions,
      });
    }
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith(`/agents/${AGENT_ID}/opportunities/automation-policy`)) {
      if (request.method() === "GET") {
        if (state.getStatus) return json(route, { detail: "hidden server detail" }, state.getStatus);
        return json(route, state.policy);
      }
      if (request.method() === "PUT") {
        const body = request.postDataJSON() as Record<string, unknown>;
        state.updates.push(body);
        if (state.conflictOnce) {
          state.conflictOnce = false;
          state.policy = { ...state.policy, timezone: "America/Lima", version: 4 };
          return json(route, { detail: "automation policy version changed" }, 409);
        }
        state.policy = {
          ...state.policy,
          ...body,
          allowed_kinds: body.allowed_kinds as string[],
          quiet_hours_start: body.quiet_hours_start as string | null,
          quiet_hours_end: body.quiet_hours_end as string | null,
          version: state.policy.version + 1,
        } as TestPolicy;
        return json(route, state.policy);
      }
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

test("loads and updates the agent policy with its CAS version", async ({ page }) => {
  const state: PolicyState = { policy: defaultPolicy(), updates: [] };
  await prepare(page, state);
  await page.goto(`/agents/${AGENT_ID}/automation-policy`);

  await expect(page.getByText("Deshabilitada: no autoriza ejecuciones automáticas.")).toBeVisible();
  await page.getByLabel("Automatización habilitada").check();
  await page.getByLabel("Permitir seguimiento comercial").check();
  await page.getByLabel("Zona horaria IANA").fill("America/Argentina/Salta");
  await page.getByLabel("Aplicar horario de silencio").check();
  await page.getByLabel("Inicio del silencio").fill("21:30");
  await page.getByLabel("Fin del silencio").fill("08:30");
  await page.getByLabel("Intentos máximos").fill("5");
  await page.getByRole("button", { name: "Guardar política" }).first().click();

  await expect.poll(() => state.updates.length).toBe(1);
  expect(state.updates[0]).toMatchObject({
    expected_version: 0,
    is_enabled: true,
    allowed_kinds: ["commercial_follow_up"],
    timezone: "America/Argentina/Salta",
    quiet_hours_start: "21:30",
    quiet_hours_end: "08:30",
    max_attempts: 5,
  });
  await expect(page.getByText("Política comercial guardada.")).toBeFocused();
  await expect(page.getByText("Versión de política 1")).toBeVisible();
});

test("navigation and dashboard expose the agent-scoped policy", async ({ page }) => {
  const state: PolicyState = { policy: defaultPolicy(), updates: [] };
  await prepare(page, state);
  await page.goto(`/agents/${AGENT_ID}/overview`);

  await expect(
    page.locator("#panel-content").getByRole("link", { name: /^Política comercial/ }),
  ).toHaveAttribute("href", `/agents/${AGENT_ID}/automation-policy`);
  await expect(
    page.locator("#admin-navigation").getByRole("link", { name: "Política comercial" }),
  ).toHaveAttribute("href", `/agents/${AGENT_ID}/automation-policy`);
});

test("a CAS conflict refreshes the latest policy before another edit", async ({ page }) => {
  const state: PolicyState = { policy: defaultPolicy(), updates: [], conflictOnce: true };
  await prepare(page, state);
  await page.goto(`/agents/${AGENT_ID}/automation-policy`);

  await page.getByRole("button", { name: "Guardar política" }).first().click();

  await expect(
    page.getByText(/la política cambió en otra sesión.*recargamos la última versión/i),
  ).toBeFocused();
  await expect(page.getByLabel("Zona horaria IANA")).toHaveValue("America/Lima");
  await expect(page.getByText("Versión de política 4")).toBeVisible();
  expect(state.updates[0]).toMatchObject({ expected_version: 0 });
});

test("read permission never implies policy management", async ({ page }) => {
  const state: PolicyState = { policy: defaultPolicy(), updates: [] };
  await prepare(page, state, ["profiles.read", "opportunities.read"]);
  await page.goto(`/agents/${AGENT_ID}/automation-policy`);

  await expect(page.getByText(/acceso de solo lectura/i)).toBeVisible();
  await expect(page.getByLabel("Automatización habilitada")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Guardar política" })).toHaveCount(0);
});

test("forbidden policy responses do not expose server details", async ({ page }) => {
  const state: PolicyState = { policy: defaultPolicy(), updates: [], getStatus: 403 };
  await prepare(page, state);
  await page.goto(`/agents/${AGENT_ID}/automation-policy`);

  await expect(page.getByRole("alert")).toHaveText("No se pudo acceder a la política de este agente.");
  await expect(page.getByText("hidden server detail")).toHaveCount(0);
});

test("mobile policy controls remain labelled and avoid horizontal overflow", async ({ page }) => {
  const state: PolicyState = { policy: defaultPolicy(), updates: [] };
  await prepare(page, state);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/agents/${AGENT_ID}/automation-policy`);

  await expect(page.getByLabel("Automatización habilitada")).toBeVisible();
  await expect(page.getByLabel("Zona horaria IANA")).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
