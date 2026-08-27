import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_A = "00000000-0000-0000-0000-0000000000a1";
const AGENT_B = "00000000-0000-0000-0000-0000000000b2";
const SOURCE_A = "10000000-0000-0000-0000-0000000000a1";
const SOURCE_B = "10000000-0000-0000-0000-0000000000b2";

const admin = {
  id: "20000000-0000-0000-0000-000000000001",
  email: "admin@example.test",
  name: "Admin",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["*"],
};

const profile = (id: string, name: string, slug: string, active: boolean) => ({
  id, name, slug, version: 1, is_active: active, is_public: active, retention_days: 30,
  description: `${name} description`, prompt_identity: "Identity", prompt_domain: "Domain",
  prompt_guardrails: "Guardrails", unauthorized_message: "Unauthorized", error_message: "Error",
  created_at: "2026-08-27T10:00:00Z", updated_at: "2026-08-27T10:00:00Z",
});

const source = (id: string, name: string, slug: string, credentials = false) => ({
  id, name, slug, source_type: "http", base_url: `https://${slug}.example.test`,
  allowed_hosts: [`${slug}.example.test`], auth_type: credentials ? "bearer" : "none",
  auth_config: {}, default_headers: { Accept: "application/json" }, has_credentials: credentials,
  is_active: true, is_public: false, verify_tls: true, allow_private_network: false,
  timeout_seconds: 30, max_response_bytes: 2_000_000,
});

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function mockWorkspace(page: Page) {
  let assignedSourceIds = new Set([SOURCE_A]);
  await page.addInitScript(() => {
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" }));
  });
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/profiles/")) return json(route, [profile(AGENT_A, "Agent Alpha", "alpha", true), profile(AGENT_B, "Agent Beta", "beta", true)]);
    if (path.endsWith(`/agents/${AGENT_A}/sources`) || path.endsWith(`/agents/${AGENT_B}/sources`)) {
      return json(route, [source(SOURCE_A, "CRM Alpha", "crm-alpha", true), source(SOURCE_B, "ERP Beta", "erp-beta")].filter((item) => assignedSourceIds.has(item.id)));
    }
    const assignment = path.match(/\/agents\/[^/]+\/sources\/([^/]+)$/);
    if (assignment && request.method() === "PUT") {
      assignedSourceIds.add(assignment[1]);
      return route.fulfill({ status: 204 });
    }
    if (assignment && request.method() === "DELETE") {
      assignedSourceIds.delete(assignment[1]);
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/sources/")) return json(route, [source(SOURCE_A, "CRM Alpha", "crm-alpha", true), source(SOURCE_B, "ERP Beta", "erp-beta")]);
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

test("agent selection is URL-owned and survives refresh", async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/agents/${AGENT_A}/overview`);
  await expect(page.locator("#panel-content").getByRole("heading", { name: "Agent Alpha", exact: true })).toBeVisible();
  await expect(page.getByLabel("Agente de trabajo")).toHaveValue(AGENT_A);

  await page.reload();
  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_A}/overview$`));
  await expect(page.getByLabel("Agente de trabajo")).toHaveValue(AGENT_A);

  await page.getByLabel("Agente de trabajo").selectOption(AGENT_B);
  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_B}/overview$`));
  await expect(page.locator("#panel-content").getByRole("heading", { name: "Agent Beta", exact: true })).toBeVisible();
});

test("source library assignment uses the selected agent contract", async ({ page }) => {
  await mockWorkspace(page);
  await page.goto(`/agents/${AGENT_A}/sources`);
  await expect(page.getByRole("heading", { name: "Asignadas (1)" })).toBeVisible();
  const available = page.getByRole("heading", { name: "Disponibles en la biblioteca (1)" }).locator("..");
  await available.getByRole("button", { name: "Asignar" }).click();
  await expect(page.getByRole("heading", { name: "Asignadas (2)" })).toBeVisible();
});

test("mobile agent navigation uses a vertical drawer without horizontal overflow", async ({ page }) => {
  await mockWorkspace(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/agents/${AGENT_A}/overview`);
  await page.getByRole("button", { name: "Abrir navegación" }).click();
  await expect(page.getByRole("navigation", { name: "Navegación del panel" })).toBeVisible();
  await page.getByRole("link", { name: "Fuentes", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_A}/sources$`));
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
