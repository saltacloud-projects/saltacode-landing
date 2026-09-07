import { expect, type Page, type Route, test } from "@playwright/test";

const AGENT_A = "00000000-0000-0000-0000-0000000000a1";
const AGENT_B = "00000000-0000-0000-0000-0000000000b2";
const profile = (id: string, name: string, active: boolean) => ({
  id,
  name,
  slug: name.toLowerCase().replaceAll(" ", "-"),
  version: 1,
  is_active: active,
  is_public: false,
  retention_days: 30,
  description: "Specialized agent",
  prompt_identity: "Identity",
  prompt_domain: "Domain",
  prompt_guardrails: "Limits",
  unauthorized_message: "",
  error_message: "",
  created_at: "2026-09-07T10:00:00Z",
  updated_at: "2026-09-07T10:00:00Z",
});
const adapters = [
  ["web", "web_builtin", true],
  ["whatsapp", "meta_whatsapp_cloud", true],
  ["email", "email", false],
  ["instagram_dm", "meta_instagram_graph", false],
  ["facebook_messenger", "meta_messenger_graph", false],
].map(([channel, adapter_key, implemented]) => ({
  channel,
  adapter_key,
  adapter_implemented: implemented,
  implementation_status: implemented ? "implemented" : "planned",
  capabilities: [],
  credentials_required: channel !== "web",
  blocking_codes: implemented ? [] : ["adapter_not_implemented"],
}));

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function mockPlatform(
  page: Page,
  options: { createStatus?: number; permissions?: string[] } = {},
) {
  const profiles = [profile(AGENT_A, "Existing Agent", true)];
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  await page.addInitScript(() =>
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" })),
  );
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path.endsWith("/auth/me"))
      return json(route, {
        id: "20000000-0000-0000-0000-000000000001",
        email: "operator@example.test",
        name: "Operator",
        role: "admin",
        is_active: true,
        must_change_password: false,
        permissions: options.permissions ?? ["*"],
      });
    if (path.endsWith("/profiles/") && method === "POST") {
      const body = route.request().postDataJSON();
      writes.push({ path, body });
      if (options.createStatus)
        return json(route, { detail: "agent_slug_conflict" }, options.createStatus);
      const created = { ...profile(AGENT_B, "New Advisor", false), ...body };
      profiles.push(created);
      return json(route, created, 201);
    }
    if (path.endsWith("/profiles/")) return json(route, profiles);
    if (path.endsWith("/runtime")) return json(route, { detail: "Runtime not configured" }, 404);
    if (path.endsWith("/activate")) {
      writes.push({ path, body: {} });
      const agent = profiles.find((item) => path.includes(item.id));
      if (agent) agent.is_active = true;
      return json(route, agent);
    }
    if (path.endsWith("/channel-catalog")) return json(route, { adapters, connections: [] });
    if (path.endsWith("/channel-connections") || path.endsWith("/routes")) return json(route, []);
    return json(route, { detail: `Unmocked ${method} ${path}` }, 500);
  });
  return { writes, profiles };
}

async function fillAgent(page: Page) {
  await page.getByRole("button", { name: "Crear agente", exact: true }).click();
  await expect(page.getByLabel("Nombre", { exact: true })).toBeFocused();
  await page.getByLabel("Nombre", { exact: true }).fill("New Advisor");
  await page.getByLabel("Identificador único").fill("new-advisor");
  await page.getByLabel("Identidad y presentación").fill("I am an independent advisor.");
  await page.getByLabel("Especialización", { exact: true }).fill("Commercial questions.");
  await page.getByLabel("Límites de comportamiento").fill("Never invent consent or prices.");
}

test("create independent inactive agent then configure and activate without disabling existing agents", async ({
  page,
}) => {
  const fixture = await mockPlatform(page);
  await page.goto("/agents");
  await fillAgent(page);
  await page.getByRole("button", { name: "Crear y configurar" }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_B}/identity$`));
  await expect(page.getByRole("heading", { name: "Identidad de New Advisor" })).toBeVisible();
  await expect(page.getByText(/Runtime pendiente de configurar/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Modelo y límites", exact: true })).toHaveAttribute(
    "href",
    `/agents/${AGENT_B}/runtime`,
  );
  expect(fixture.writes[0].body).toMatchObject({
    slug: "new-advisor",
    is_public: false,
    prompt_domain: "Commercial questions.",
    retention_days: 30,
  });
  expect(fixture.profiles.map((item) => item.is_active)).toEqual([true, false]);
  await page.getByRole("button", { name: "Habilitar agente" }).click();
  await expect(page.getByRole("button", { name: "Habilitar agente" })).toHaveCount(0);
  expect(fixture.profiles.map((item) => item.is_active)).toEqual([true, true]);
});

for (const status of [409, 403])
  test(`creation ${status} remains recoverable and preserves entered configuration`, async ({
    page,
  }) => {
    const fixture = await mockPlatform(page, { createStatus: status });
    await page.goto("/agents");
    await fillAgent(page);
    await page.getByRole("button", { name: "Crear y configurar" }).click();
    await expect(page.getByRole("alert")).toContainText(
      status === 409 ? "identificador ya está en uso" : "No tenés permiso",
    );
    await expect(page.getByLabel("Nombre", { exact: true })).toHaveValue("New Advisor");
    expect(fixture.profiles).toHaveLength(1);
  });

test("read-only operator cannot create agents", async ({ page }) => {
  await mockPlatform(page, { permissions: ["profiles.read"] });
  await page.goto("/agents");
  await expect(page.getByRole("heading", { name: "Agentes", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Crear agente", exact: true })).toHaveCount(0);
});

test("mobile creation supports keyboard cancel and no horizontal overflow", async ({ page }) => {
  await mockPlatform(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/agents");
  await fillAgent(page);
  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport);
  await page.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(page.getByRole("button", { name: "Crear agente", exact: true })).toBeFocused();
});

test("global channels distinguish adapters from activation and route to explicit agent", async ({
  page,
}) => {
  const fixture = await mockPlatform(page);
  await page.goto("/channels");
  await expect(page.getByRole("heading", { name: "Canales", exact: true })).toBeVisible();
  await expect(page.getByText("Adaptador disponible", { exact: true })).toHaveCount(2);
  await expect(page.getByText("Integración pendiente", { exact: true })).toHaveCount(3);
  await expect(
    page.getByRole("link", { name: "Administrar conexiones y credenciales" }),
  ).toHaveAttribute("href", "/channels/connections");
  await page.getByRole("link", { name: /Existing Agent Configurar rutas/ }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_A}/channels$`));
  expect(fixture.writes).toEqual([]);
});
