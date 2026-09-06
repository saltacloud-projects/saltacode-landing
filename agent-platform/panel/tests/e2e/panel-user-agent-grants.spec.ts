import { expect, test, type Page, type Route } from "@playwright/test";

const ADMIN_ID = "20000000-0000-0000-0000-000000000001";
const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";

const admin = {
  id: ADMIN_ID,
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
  created_at: "2026-09-06T10:00:00Z",
  updated_at: "2026-09-06T10:00:00Z",
};

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function mockPanel(page: Page, methods: string[]) {
  let isGranted = false;
  await page.addInitScript(() => {
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" }));
  });
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith("/panel-users/roles")) {
      return json(route, [
        {
          key: "admin",
          name: "Administrator",
          description: "Full platform administration",
          permissions: ["*"],
          is_active: true,
          is_system: true,
        },
      ]);
    }
    if (path.endsWith(`/panel-users/${ADMIN_ID}/agent-grants/${AGENT_ID}`)) {
      methods.push(request.method());
      if (request.method() === "PUT") {
        expect(request.postDataJSON()).toEqual({ permissions: ["*"] });
        isGranted = true;
        return json(route, { detail: "updated" });
      }
      isGranted = false;
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith(`/panel-users/${ADMIN_ID}/agent-grants`)) {
      return json(route, {
        user_id: ADMIN_ID,
        available_permissions: ["*", "profiles.read", "opportunities.read"],
        agents: [
          { id: AGENT_ID, name: "Agent Alpha", slug: "alpha", is_active: true },
        ],
        grants: isGranted
          ? [
              {
                id: "30000000-0000-0000-0000-000000000001",
                agent_id: AGENT_ID,
                agent_name: "Agent Alpha",
                agent_slug: "alpha",
                permissions: ["*"],
                is_active: true,
              },
            ]
          : [],
      });
    }
    if (path.endsWith("/panel-users/")) return json(route, [admin]);
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

test("panel administrator can assign and revoke an agent grant", async ({ page }) => {
  const methods: string[] = [];
  await mockPanel(page, methods);
  await page.goto("/panel-users");

  await page.getByTitle("Administrar agentes").click();
  const agentToggle = page.getByLabel(/Agent Alpha/).first();
  await expect(agentToggle).not.toBeChecked();
  await agentToggle.check();
  await expect(page.getByLabel("Acceso completo al agente")).toBeChecked();
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect(agentToggle).toBeChecked();

  await agentToggle.uncheck();
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect(agentToggle).not.toBeChecked();
  expect(methods).toEqual(["PUT", "DELETE"]);
});
