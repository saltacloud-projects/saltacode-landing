import { expect, type Page, type Route, test } from "@playwright/test";

const AGENT = "00000000-0000-0000-0000-0000000000a1";
const OTHER_AGENT = "00000000-0000-0000-0000-0000000000b2";

async function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockPipeline(page: Page, { conflict = false, readOnly = false } = {}) {
  let policy = {
    agent_id: AGENT,
    quote_request_action: "handoff",
    version: 0,
    is_configured: false,
  };
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const permissions = readOnly ? ["runtime.read"] : ["runtime.read", "runtime.manage"];
  await page.addInitScript(() =>
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" })),
  );
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me"))
      return json(route, {
        id: "operator",
        email: "operator@example.test",
        name: "Operator",
        role: "custom",
        permissions,
        is_active: true,
        must_change_password: false,
      });
    if (path.endsWith("/crm/automation/agents"))
      return json(route, [
        { id: AGENT, name: "Commercial advisor", is_active: true, capabilities: permissions },
        { id: OTHER_AGENT, name: "Specialist", is_active: true, capabilities: ["runtime.read"] },
      ]);
    if (path.endsWith(`/agents/${OTHER_AGENT}/progression-policy`))
      return json(route, { ...policy, agent_id: OTHER_AGENT });
    if (path.endsWith(`/agents/${AGENT}/progression-policy`)) {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON();
        writes.push({ path, body });
        if (conflict) {
          policy = { ...policy, version: 4, is_configured: true };
          return json(route, { detail: "Conflict" }, 409);
        }
        policy = {
          ...policy,
          quote_request_action: body.quote_request_action,
          version: policy.version + 1,
          is_configured: true,
        };
      }
      return json(route, policy);
    }
    return json(route, { detail: `Unmocked ${path}` }, 500);
  });
  return writes;
}

test("guided pipeline config works with runtime grant without profile listing permission", async ({
  page,
}) => {
  const writes = await mockPipeline(page);
  await page.goto("/pipeline");
  await expect(
    page.getByRole("heading", { name: "Pipeline comercial", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/no un planificador autónomo completo/)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Qué requiere integración externa" }),
  ).toBeVisible();
  await page.getByLabel("Agente cuya política vas a configurar").selectOption(AGENT);
  await expect(page.getByText(/Sin decisión explícita guardada/)).toBeVisible();
  await page.getByRole("radio", { name: /Continuar con el mismo agente/ }).check();
  await page.getByRole("button", { name: "Guardar política" }).click();
  await expect(page.getByRole("status")).toContainText("Política guardada para este agente");
  expect(writes).toEqual([
    {
      path: `/api/admin/agents/${AGENT}/progression-policy`,
      body: { expected_version: 0, quote_request_action: "keep_agent" },
    },
  ]);
  await page.reload();
  await expect(page.getByLabel("Agente cuya política vas a configurar")).toHaveValue("");
  await page.getByLabel("Agente cuya política vas a configurar").selectOption(AGENT);
  await expect(page.getByRole("radio", { name: /Continuar con el mismo agente/ })).toBeChecked();
});

test("stale progression policy cannot be overwritten before explicit reload", async ({ page }) => {
  const writes = await mockPipeline(page, { conflict: true });
  await page.goto("/pipeline");
  await page.getByLabel("Agente cuya política vas a configurar").selectOption(AGENT);
  await page.getByRole("radio", { name: /Continuar con el mismo agente/ }).check();
  await page.getByRole("button", { name: "Guardar política" }).click();
  await expect(page.getByRole("alert")).toContainText("cambió en otra sesión");
  await expect(page.getByRole("button", { name: "Guardar política" })).toBeDisabled();
  expect(writes).toHaveLength(1);
  await page.getByRole("button", { name: "Recargar política" }).click();
  await expect(page.getByText(/Versión 4/)).toBeVisible();
  await expect(
    page.getByRole("radio", { name: /Derivar a un agente especializado/ }),
  ).toBeChecked();
});

test("specific agent grant disables write even when role allows managing another agent", async ({
  page,
}) => {
  const writes = await mockPipeline(page);
  await page.goto("/pipeline");
  await page.getByLabel("Agente cuya política vas a configurar").selectOption(OTHER_AGENT);
  await expect(page.getByRole("radio", { name: /Continuar con el mismo agente/ })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Guardar política" })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test("read-only policy and mobile layout preserve guided access", async ({ page }) => {
  await mockPipeline(page, { readOnly: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/pipeline");
  await page.getByLabel("Agente cuya política vas a configurar").selectOption(AGENT);
  await expect(page.getByRole("button", { name: "Guardar política" })).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Intervención humana en cualquier etapa" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});
