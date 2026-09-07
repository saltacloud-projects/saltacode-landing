import { expect, type Page, type Route, test } from "@playwright/test";

const A = "00000000-0000-0000-0000-0000000000a1";
const B = "00000000-0000-0000-0000-0000000000b2";
const ADMIN = "10000000-0000-0000-0000-000000000001";
const CHAT = "20000000-0000-0000-0000-000000000002";
const TASK = "30000000-0000-0000-0000-000000000003";
const permissions = [
  "conversations.read",
  "conversations.manage",
  "opportunities.read",
  "meetings.read",
  "follow_ups.read",
  "follow_ups.manage",
  "deliveries.read",
  "inbound.read",
  "audit.read",
];
const admin = {
  id: ADMIN,
  email: "operator@example.test",
  name: "Operator",
  role: "operator",
  permissions,
  is_active: true,
  must_change_password: false,
};
const catalog = [
  { id: A, name: "Entrada", is_active: true, capabilities: ["conversations.read"] },
  { id: B, name: "Especialista", is_active: true, capabilities: permissions },
];
async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}
async function prepare(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" })),
  );
}
function conversation(owner = B) {
  return {
    id: CHAT,
    principal_id: "visitor",
    display_name: "Consulta web",
    channel: "web",
    route_key: "website",
    status: "active",
    control_mode: "automated",
    control_version: 2,
    routing_agent: { id: owner, name: owner === A ? "Entrada" : "Especialista" },
    automation_agent: { id: A, name: "Entrada" },
    automation_version: 4,
    assigned_operator: null,
    control_changed_at: "2026-09-07T10:00:00Z",
    control_reason: null,
    message_count: 0,
    last_activity_at: "2026-09-07T10:00:00Z",
    owner_agent_id: owner,
    owner_agent_name: owner === A ? "Entrada" : "Especialista",
    capabilities:
      owner === A ? ["conversations.read"] : ["conversations.read", "conversations.manage"],
  };
}

test("CRM home loads one paginated authorized collection without profile permission", async ({
  page,
}) => {
  await prepare(page);
  const requests: URL[] = [];
  await page.route("**/api/admin/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    if (url.pathname.endsWith("/auth/me")) return json(route, admin);
    if (url.pathname.endsWith("/crm/inbox/agents")) return json(route, catalog);
    if (url.pathname.endsWith("/crm/inbox"))
      return json(route, {
        items: [conversation()],
        total: 70,
        limit: 50,
        offset: Number(url.searchParams.get("offset")),
      });
    return json(route, { detail: "Unexpected request" }, 500);
  });
  await page.goto("/");
  await expect(page).toHaveURL(/\/inbox$/);
  await expect(page.getByRole("heading", { name: "Inbox", exact: true })).toBeVisible();
  await expect(page.getByLabel("Configurar agente", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Agente de ingreso")).toHaveValue("");
  await expect(page.getByText("1–50 de 70")).toBeVisible();
  await page.getByRole("button", { name: "Siguiente", exact: true }).click();
  await expect(page.getByText("51–70 de 70")).toBeVisible();
  expect(
    requests.some(
      (url) => url.pathname.endsWith("/crm/inbox") && url.searchParams.get("offset") === "50",
    ),
  ).toBe(true);
  await page.getByText("Filtros y alcance", { exact: true }).click();
  await page.getByLabel("Agente de ingreso").selectOption(A);
  await expect(page.getByText("1–50 de 70")).toBeVisible();
  await expect
    .poll(() =>
      requests
        .filter((url) => url.pathname.endsWith("/crm/inbox"))
        .at(-1)
        ?.searchParams.get("agent_id"),
    )
    .toBe(A);
  expect(requests.some((url) => /\/profiles|\/agents\//.test(url.pathname))).toBe(false);
});

test("global inbox uses item owner for commands and keeps per-item capability restrictions", async ({
  page,
}) => {
  await prepare(page);
  const commands: string[] = [];
  const rows = [
    { ...conversation(A), id: "read-only", display_name: "Solo lectura" },
    conversation(),
  ];
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/crm/inbox/agents")) return json(route, catalog);
    if (path.endsWith("/crm/inbox"))
      return json(route, { items: rows, total: 2, limit: 50, offset: 0 });
    if (path.endsWith("/inbox/operators")) return json(route, []);
    if (path.endsWith("/control-transitions")) {
      commands.push(path);
      return json(route, {});
    }
    const row = rows.find((item) => path.endsWith(`/inbox/${item.id}`));
    if (row) {
      const { capabilities, owner_agent_id, owner_agent_name, ...detail } = row;
      return json(route, { conversation: detail, messages: [], control_events: [] });
    }
    return json(route, { detail: "Unexpected request" }, 500);
  });
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Solo lectura/ }).click();
  await expect(page.getByRole("button", { name: "Tomar control" })).toHaveCount(0);
  await page.getByRole("button", { name: /Consulta web/ }).click();
  await page.getByRole("button", { name: "Tomar control" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0]).toBe(`/api/admin/agents/${B}/inbox/${CHAT}/control-transitions`);
});

test("follow-up commands use current owner rather than scheduled assignment", async ({ page }) => {
  await prepare(page);
  const commands: string[] = [];
  const row = {
    id: TASK,
    opportunity_id: "opportunity",
    assigned_agent_id: A,
    assigned_operator_id: null,
    owner_agent_id: B,
    owner_agent_name: "Especialista",
    capabilities: ["follow_ups.read", "follow_ups.manage"],
    kind: "commercial_follow_up",
    status: "scheduled",
    state_version: 3,
    due_at: "2026-09-08T10:00:00Z",
    available_at: "2026-09-08T10:00:00Z",
    attempts: 0,
    max_attempts: 3,
    is_leased: false,
    outbound_status: null,
    safe_code: null,
    review_required_at: null,
    created_at: "2026-09-07T10:00:00Z",
    updated_at: "2026-09-07T10:00:00Z",
  };
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/crm/follow-ups/agents")) return json(route, catalog);
    if (path.endsWith("/crm/follow-ups"))
      return json(route, { items: [row], total: 1, limit: 50, offset: 0 });
    if (path === `/api/admin/agents/${B}/follow-ups/${TASK}/events`)
      return json(route, { items: [], total: 0, limit: 100, offset: 0 });
    if (path === `/api/admin/agents/${B}/follow-ups/${TASK}/cancel`) {
      commands.push(path);
      row.status = "cancelled";
      return json(route, {});
    }
    if (path === `/api/admin/agents/${B}/follow-ups/${TASK}`)
      return json(route, {
        ...row,
        scheduled_policy_version: null,
        executed_policy_version: null,
        quote_version_id: null,
        conversation_id: null,
      });
    return json(route, { detail: "Wrong owner" }, 404);
  });
  await page.goto("/follow-ups");
  await page.getByRole("button", { name: /Seguimiento 30000000/ }).click();
  await page.getByRole("button", { name: "Cancelar seguimiento" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0]).toContain(`/agents/${B}/`);
});

for (const [resource, title] of [
  ["opportunities", "Oportunidades"],
  ["meetings", "Reuniones"],
  ["deliveries", "Entregas"],
  ["inbound-jobs", "Ingresos externos"],
  ["audit", "Auditoría"],
]) {
  test(`global ${resource} is available without profile permission`, async ({ page }) => {
    await prepare(page);
    const unexpected: string[] = [];
    await page.route("**/api/admin/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/auth/me")) return json(route, admin);
      if (path.endsWith("/crm/inbox/live"))
        return route.fulfill({
          contentType: "text/event-stream",
          body: 'event: inbox.snapshot\ndata: {"revision":"empty","unread_conversations":0,"active_conversations":0,"historical_conversations":0}\n\n',
        });
      if (path.endsWith(`/crm/${resource}/agents`)) return json(route, catalog);
      if (path.endsWith(`/crm/${resource}`))
        return json(route, { items: [], total: 0, limit: 50, offset: 0 });
      unexpected.push(path);
      return json(route, { detail: "Unexpected request" }, 500);
    });
    await page.goto(`/${resource}`);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await expect(page.getByText("Sin resultados", { exact: true })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(unexpected).toEqual([]);
  });
}

test("mobile CRM navigation restores focus without horizontal overflow", async ({ page }) => {
  await prepare(page);
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/agents")) return json(route, catalog);
    return json(route, { items: [], total: 0, limit: 50, offset: 0 });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/inbox");
  await page.getByRole("button", { name: "Abrir navegación" }).click();
  await expect(
    page.locator("#admin-navigation").getByRole("link", { name: "Inbox", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Configurar agente", { exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Abrir navegación" })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test("a meeting created globally retains explicit owner and granted actions", async ({ page }) => {
  await prepare(page);
  const opportunity = "40000000-0000-0000-0000-000000000004";
  const meetingId = "50000000-0000-0000-0000-000000000005";
  const granted = [...permissions, "meetings.manage"];
  const commands: string[] = [];
  let created = false;
  const meeting = {
    id: meetingId,
    opportunity_id: opportunity,
    conversation_id: null,
    status: "requested",
    state_version: 1,
    proposal_version: 0,
    selected_slot: null,
    requested_at: "2026-09-07T10:00:00Z",
    created_at: "2026-09-07T10:00:00Z",
    updated_at: "2026-09-07T10:00:00Z",
    agent_id: B,
    scheduled_at: null,
  };
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, { ...admin, permissions: granted });
    if (path.endsWith("/crm/meetings/agents"))
      return json(route, [{ ...catalog[1], capabilities: granted }]);
    if (path.endsWith("/crm/meetings"))
      return json(route, {
        items: created
          ? [
              {
                ...meeting,
                owner_agent_id: B,
                owner_agent_name: "Especialista",
                capabilities: granted,
              },
            ]
          : [],
        total: created ? 1 : 0,
        limit: 50,
        offset: 0,
      });
    if (path === `/api/admin/agents/${B}/meetings/` && request.method() === "POST") {
      commands.push(path);
      created = true;
      return json(route, { id: meetingId, applied: true, duplicate: false, state_version: 1 });
    }
    if (path === `/api/admin/agents/${B}/meetings/${meetingId}`)
      return json(route, { ...meeting, slots: [], events: [] });
    return json(route, { detail: "Unexpected request" }, 500);
  });
  await page.goto(`/meetings?agent_id=${B}&opportunity_id=${opportunity}`);
  await page.getByRole("button", { name: "Crear reunión", exact: true }).click();
  await expect.poll(() => commands.length).toBe(1);
  await expect(page.getByRole("heading", { name: "Proponer horarios" })).toBeVisible();
  await expect(page.getByLabel("Responsable comercial")).toHaveValue(B);
  await expect(page.getByRole("alert")).toHaveCount(0);
});
