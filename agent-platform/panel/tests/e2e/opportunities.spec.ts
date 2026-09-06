import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";
const OTHER_AGENT_ID = "00000000-0000-0000-0000-0000000000b2";
const ADMIN_ID = "10000000-0000-0000-0000-000000000001";
const CONTACT_ID = "20000000-0000-0000-0000-000000000001";
const PRINCIPAL_ID = "30000000-0000-0000-0000-000000000001";
const CONVERSATION_ID = "40000000-0000-0000-0000-000000000001";
const OPPORTUNITY_ID = "50000000-0000-0000-0000-000000000001";

const admin = {
  id: ADMIN_ID,
  email: "operator@example.test",
  name: "Operator",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["*"],
};

const profiles = [
  {
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
  },
  {
    id: OTHER_AGENT_ID,
    name: "Agente de oportunidades",
    slug: "opportunities",
    version: 1,
    is_active: true,
    is_public: false,
    retention_days: 30,
    description: "Opportunity agent",
    prompt_identity: "Identity",
    prompt_domain: "Domain",
    prompt_guardrails: "Guardrails",
    unauthorized_message: "Unauthorized",
    error_message: "Error",
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:00:00Z",
  },
];

function contact(consent = false) {
  return {
    id: CONTACT_ID,
    principal_id: PRINCIPAL_ID,
    display_name: "Lead web",
    company_name: "Example SA",
    job_title: "Founder",
    status: "active",
    contact_points: [
      {
        id: "60000000-0000-0000-0000-000000000001",
        kind: "email",
        masked_value: "l***@example.test",
        verification_status: "verified",
        commercial_follow_up_allowed: consent,
        quote_delivery_allowed: false,
      },
    ],
  };
}

interface State {
  stage: string;
  version: number;
  quoteRequests: Array<Record<string, unknown>>;
}

function summary(state: State) {
  return {
    id: OPPORTUNITY_ID,
    title: "Nuevo sistema comercial",
    summary: "Discovery inicial",
    stage: state.stage,
    control_version: state.version,
    contact: { ...contact(), contact_points: [] },
    assigned_agent: { id: AGENT_ID, name: "Agente comercial" },
    assigned_operator: { id: ADMIN_ID, name: "Operator", email: "operator@example.test" },
    linked_conversation_count: 1,
    pending_follow_up_count: 0,
    latest_quote_status: state.quoteRequests.at(0)?.status ?? null,
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:00:00Z",
    closed_at: null,
  };
}

function detail(state: State) {
  return {
    ...summary(state),
    contact: contact(),
    available_conversations: [],
    conversations: [
      {
        id: "70000000-0000-0000-0000-000000000001",
        conversation_id: CONVERSATION_ID,
        channel: "web",
        route_key: "saltacode-landing",
        status: "active",
        linked_at: "2026-09-06T10:00:00Z",
      },
    ],
    stage_events: [
      {
        id: "80000000-0000-0000-0000-000000000001",
        event_type: "created",
        from_stage: null,
        to_stage: "new",
        control_version: 0,
        reason: null,
        created_at: "2026-09-06T10:00:00Z",
      },
    ],
    ownership_events: [],
    follow_ups: [],
    quote_requests: state.quoteRequests,
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
  state: State,
  commands: Array<{ path: string; body: Record<string, unknown>; key?: string }>,
) {
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/profiles/")) return json(route, profiles);
    if (path.endsWith("/opportunities/candidates")) {
      return json(route, [
        {
          contact: contact(),
          conversation_id: CONVERSATION_ID,
          channel: "web",
          route_key: "saltacode-landing",
          conversation_status: "active",
          conversation_updated_at: "2026-09-06T10:00:00Z",
        },
      ]);
    }
    if (path.endsWith("/opportunities/operators")) return json(route, [admin]);
    if (path.endsWith("/opportunities/") && request.method() === "GET") {
      return json(route, { items: [summary(state)], total: 1, limit: 100, offset: 0 });
    }
    if (path.endsWith(`/opportunities/${OPPORTUNITY_ID}`) && request.method() === "GET") {
      return json(route, detail(state));
    }
    if (path.endsWith("/opportunities/") && request.method() === "POST") {
      commands.push({
        path,
        body: request.postDataJSON(),
        key: request.headers()["idempotency-key"],
      });
      return json(route, { ...summary(state), created: true }, 201);
    }
    if (path.endsWith(`/opportunities/${OPPORTUNITY_ID}/stage-transitions`)) {
      const body = request.postDataJSON();
      commands.push({ path, body, key: request.headers()["idempotency-key"] });
      state.stage = String(body.target_stage);
      state.version += 1;
      return json(route, {
        id: OPPORTUNITY_ID,
        stage: state.stage,
        control_version: state.version,
        assigned_agent_id: AGENT_ID,
        assigned_operator_id: ADMIN_ID,
        created: true,
      });
    }
    if (path.endsWith(`/opportunities/${OPPORTUNITY_ID}/quote-requests`)) {
      const body = request.postDataJSON();
      commands.push({ path, body, key: request.headers()["idempotency-key"] });
      state.quoteRequests.unshift({
        id: "90000000-0000-0000-0000-000000000001",
        status: body.status,
        state_version: 0,
        requirements: body.requirements,
        failure_code: body.failure_code,
        created_at: "2026-09-06T10:05:00Z",
        updated_at: "2026-09-06T10:05:00Z",
        versions: [],
      });
      return json(route, {}, 201);
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

test("operator manages stage and records an honest blocked quote request", async ({ page }) => {
  await prepare(page);
  const state: State = { stage: "new", version: 0, quoteRequests: [] };
  const commands: Array<{ path: string; body: Record<string, unknown>; key?: string }> = [];
  await registerMocks(page, state, commands);

  await page.goto(`/agents/${AGENT_ID}/opportunities`);
  await page.getByRole("button", { name: /Nuevo sistema comercial/ }).click();
  await expect(page.getByText("sin consentimiento vigente", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Bloqueado: no hay un punto de contacto", { exact: false })).toBeVisible();

  await page.getByLabel("Nueva etapa").selectOption("qualified");
  await page.getByRole("button", { name: "Actualizar etapa" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].body).toMatchObject({ target_stage: "qualified", expected_version: 0 });
  expect(commands[0].key).toMatch(/^opportunity-stage-/);

  await page.getByLabel("Alcance solicitado").fill("Software a medida con discovery");
  await page.getByRole("button", { name: "Registrar solicitud" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].body).toEqual({
    requirements: { scope: "Software a medida con discovery" },
    status: "unavailable",
    failure_code: "quote_provider_unavailable",
  });
  expect(commands[1].key).toMatch(/^quote-request-/);
  await expect(page.getByText("Proveedor no disponible")).toBeVisible();
  await expect(page.getByText("La entrega por WhatsApp o email no está habilitada", { exact: false })).toBeVisible();
});

test("mobile workspace creates from a proven contact without horizontal overflow", async ({ page }) => {
  await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const state: State = { stage: "new", version: 0, quoteRequests: [] };
  const commands: Array<{ path: string; body: Record<string, unknown>; key?: string }> = [];
  await registerMocks(page, state, commands);

  await page.goto(`/agents/${AGENT_ID}/opportunities`);
  await page.getByRole("button", { name: "Nueva", exact: true }).click();
  await page.getByLabel("Título").fill("Nueva oportunidad mobile");
  await page.getByRole("button", { name: "Crear oportunidad" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].body).toMatchObject({
    contact_id: CONTACT_ID,
    source_conversation_id: CONVERSATION_ID,
    assigned_operator_id: ADMIN_ID,
  });
  expect(commands[0].key).toMatch(/^opportunity-/);

  await page.getByRole("button", { name: /Nuevo sistema comercial/ }).click();
  await expect(page.getByRole("button", { name: "Volver a oportunidades" })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
