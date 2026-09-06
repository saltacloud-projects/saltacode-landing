import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";

const admin = {
  id: "20000000-0000-0000-0000-000000000001",
  email: "admin@example.test",
  name: "Admin",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["*"],
};

const profile = {
  id: AGENT_ID,
  name: "Agent Alpha",
  slug: "alpha",
  version: 1,
  is_active: true,
  is_public: true,
  retention_days: 30,
  description: "Agent Alpha description",
  prompt_identity: "Identity",
  prompt_domain: "Domain",
  prompt_guardrails: "Guardrails",
  unauthorized_message: "Unauthorized",
  error_message: "Error",
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

async function json(route: Route, value: unknown) {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(value),
  });
}

async function mockAudit(page: Page, observedAgentIds: string[]) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "tokens",
      JSON.stringify({ access_token: "test", refresh_token: "test" }),
    );
  });
  await page.route("**/api/admin/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/me")) return json(route, admin);
    if (url.pathname.endsWith("/profiles/")) return json(route, [profile]);
    if (url.pathname.endsWith("/audit/")) {
      observedAgentIds.push(url.searchParams.get("agent_id") ?? "");
      return json(route, []);
    }
    return route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ detail: `Mock missing: ${url.pathname}` }),
    });
  });
}

test("audit is scoped to the selected agent", async ({ page }) => {
  const observedAgentIds: string[] = [];
  await mockAudit(page, observedAgentIds);

  await page.goto(`/agents/${AGENT_ID}/audit`);

  await expect(page.getByRole("heading", { name: "Auditoría", exact: true })).toBeVisible();
  await expect(page.getByText(/Eventos operativos atribuidos a Agent Alpha/)).toBeVisible();
  await expect.poll(() => observedAgentIds).toContain(AGENT_ID);
  await expect(page.getByRole("link", { name: "Auditoría", exact: true })).toBeVisible();
  await expect(page.getByText("Auditoría global")).toHaveCount(0);
});

test("legacy audit route redirects to the preferred agent", async ({ page }) => {
  const observedAgentIds: string[] = [];
  await mockAudit(page, observedAgentIds);

  await page.goto("/audit");

  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_ID}/audit$`));
  await expect.poll(() => observedAgentIds).toContain(AGENT_ID);
});
