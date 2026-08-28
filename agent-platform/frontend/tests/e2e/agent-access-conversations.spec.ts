import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_A = "00000000-0000-0000-0000-0000000000a1";
const AGENT_B = "00000000-0000-0000-0000-0000000000b2";
const USER_ID = "10000000-0000-0000-0000-0000000000a1";
const CREATED_USER_ID = "10000000-0000-0000-0000-0000000000b2";
const AREA_ID = "20000000-0000-0000-0000-0000000000a1";
const CONVERSATION_ID = "30000000-0000-0000-0000-0000000000a1";

const admin = {
  id: "40000000-0000-0000-0000-000000000001",
  email: "admin@example.test",
  name: "Admin",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["*"],
};

const profile = (id: string, name: string, slug: string) => ({
  id, name, slug, version: 1, is_active: true, is_public: true, retention_days: 30,
  description: `${name} description`, prompt_identity: "Identity", prompt_domain: "Domain",
  prompt_guardrails: "Guardrails", unauthorized_message: "Unauthorized", error_message: "Error",
  created_at: "2026-08-27T10:00:00Z", updated_at: "2026-08-27T10:00:00Z",
});

const identity = (id: string, phone: string, name: string) => ({
  id, phone_number: phone, name, notes: null, is_active: true,
  has_all_area_access: false, area_ids: [],
  created_at: "2026-08-27T10:00:00Z", updated_at: "2026-08-27T10:00:00Z",
});

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function prepare(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" }));
  });
}

function common(path: string, route: Route): Promise<void> | null {
  if (path.endsWith("/auth/me")) return json(route, admin);
  if (path.endsWith("/profiles/")) return json(route, [profile(AGENT_A, "Agent Alpha", "alpha"), profile(AGENT_B, "Agent Beta", "beta")]);
  return null;
}

test("creating a WhatsApp identity keeps identity and agent policy payloads separated", async ({ page }) => {
  await prepare(page);
  let identityBody: Record<string, unknown> | null = null;
  let assignmentBody: Record<string, unknown> | null = null;
  let assigned = false;
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const handled = common(path, route);
    if (handled) return handled;
    if (path.endsWith("/users/") && request.method() === "GET") return json(route, []);
    if (path.endsWith("/users/") && request.method() === "POST") {
      identityBody = request.postDataJSON();
      return json(route, identity(CREATED_USER_ID, "5493871234567", "Contacto nuevo"), 201);
    }
    if (path.endsWith(`/agents/${AGENT_A}/authorized-users`) && request.method() === "GET") {
      return json(route, assigned ? [{ ...identity(CREATED_USER_ID, "5493871234567", "Contacto nuevo"), agent_id: AGENT_A }] : []);
    }
    if (path.endsWith(`/agents/${AGENT_A}/authorized-users/${CREATED_USER_ID}`) && request.method() === "PUT") {
      assignmentBody = request.postDataJSON();
      assigned = true;
      return json(route, { ...identity(CREATED_USER_ID, "5493871234567", "Contacto nuevo"), agent_id: AGENT_A });
    }
    if (path.endsWith(`/agents/${AGENT_A}/document-areas`)) return json(route, []);
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });

  await page.goto(`/agents/${AGENT_A}/access`);
  await page.getByRole("button", { name: "Nueva identidad" }).click();
  await page.getByLabel("Teléfono").fill("5493871234567");
  await page.getByLabel("Nombre").fill("Contacto nuevo");
  await page.getByLabel("Notas internas").fill("Cliente web");
  await page.getByRole("button", { name: "Guardar identidad" }).click();

  await expect.poll(() => identityBody).not.toBeNull();
  expect(identityBody).toEqual({ phone_number: "5493871234567", name: "Contacto nuevo", notes: "Cliente web" });
  await expect.poll(() => assignmentBody).not.toBeNull();
  expect(assignmentBody).toEqual({ is_active: true, has_all_area_access: false, area_ids: [] });
});

test("reusing and unassigning an identity changes only the selected agent binding", async ({ page }) => {
  await prepare(page);
  let binding: Record<string, unknown> | null = null;
  let assigned = false;
  let removed = false;
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const handled = common(path, route);
    if (handled) return handled;
    if (path.endsWith("/users/")) return json(route, [identity(USER_ID, "5493871111111", "Contacto existente")]);
    if (path.endsWith(`/agents/${AGENT_A}/authorized-users`) && request.method() === "GET") {
      return json(route, assigned && !removed ? [{ ...identity(USER_ID, "5493871111111", "Contacto existente"), agent_id: AGENT_A, area_ids: [AREA_ID] }] : []);
    }
    if (path.endsWith(`/agents/${AGENT_A}/authorized-users/${USER_ID}`) && request.method() === "PUT") {
      binding = request.postDataJSON();
      assigned = true;
      return json(route, { ...identity(USER_ID, "5493871111111", "Contacto existente"), agent_id: AGENT_A, ...binding });
    }
    if (path.endsWith(`/agents/${AGENT_A}/authorized-users/${USER_ID}`) && request.method() === "DELETE") {
      removed = true;
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith(`/agents/${AGENT_A}/document-areas`)) {
      return json(route, [{ id: AREA_ID, name: "Ventas", slug: "ventas", description: null, is_general: false, is_active: true }]);
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });

  await page.goto(`/agents/${AGENT_A}/access`);
  await page.getByRole("button", { name: "Asignar" }).click();
  await page.getByLabel("Ventas").check();
  await page.getByRole("button", { name: "Guardar acceso" }).click();
  await expect.poll(() => binding).not.toBeNull();
  expect(binding).toEqual({ is_active: true, has_all_area_access: false, area_ids: [AREA_ID] });

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Quitar acceso" }).click();
  await expect.poll(() => removed).toBe(true);
  expect(assigned).toBe(true);
});

test("conversation list, history, and deletion always include the selected agent", async ({ page }) => {
  await prepare(page);
  const calls: { operation: string; agentId: string | null }[] = [];
  let deleted = false;
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const handled = common(path, route);
    if (handled) return handled;
    if (path.endsWith("/conversations/") && request.method() === "GET") {
      calls.push({ operation: "list", agentId: url.searchParams.get("agent_id") });
      const agentId = url.searchParams.get("agent_id");
      if (agentId === AGENT_B || deleted) return json(route, []);
      return json(route, [{ id: CONVERSATION_ID, agent_slug: "alpha", principal_id: USER_ID, display_name: "Visitante web", channel: "web", route_key: "landing:principal", external_thread_id: "thread-public", status: "active", message_count: 1, last_message_at: "2026-08-27T10:00:00Z", transcript_consent: true, consent_version: "v1" }]);
    }
    if (path.endsWith(`/conversations/${CONVERSATION_ID}/messages`)) {
      calls.push({ operation: "messages", agentId: url.searchParams.get("agent_id") });
      return json(route, [{ id: "message-1", role: "user", content: "Hola", status: "complete", tool_names: [], metadata: {}, created_at: "2026-08-27T10:00:00Z" }]);
    }
    if (path.endsWith(`/conversations/${CONVERSATION_ID}`) && request.method() === "DELETE") {
      calls.push({ operation: "delete", agentId: url.searchParams.get("agent_id") });
      deleted = true;
      return route.fulfill({ status: 204 });
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });

  await page.goto(`/agents/${AGENT_A}/conversations`);
  await page.getByRole("button", { name: /Visitante web/ }).click();
  await expect(page.getByText("Hola")).toBeVisible();
  await expect(page.getByText("landing:principal").first()).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Eliminar" }).click();
  await expect.poll(() => deleted).toBe(true);
  expect(calls.filter((call) => ["list", "messages", "delete"].includes(call.operation)).every((call) => call.agentId === AGENT_A)).toBe(true);

  await page.getByLabel("Agente de trabajo").selectOption(AGENT_B);
  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_B}/conversations$`));
  await expect(page.getByText("Seleccioná una conversación para revisar su historial.")).toBeVisible();
  await expect.poll(() => calls.some((call) => call.operation === "list" && call.agentId === AGENT_B)).toBe(true);
});

test("audit remains a platform-level view and legacy agent route redirects", async ({ page }) => {
  await prepare(page);
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const handled = common(path, route);
    if (handled) return handled;
    if (path.endsWith("/audit/")) return json(route, []);
    return json(route, { detail: `Mock missing: ${route.request().method()} ${path}` }, 500);
  });

  await page.goto(`/agents/${AGENT_A}/audit`);
  await expect(page).toHaveURL(/\/audit$/);
  await expect(page.getByRole("heading", { name: "Auditoría global" })).toBeVisible();
  await expect(page.getByText("Esta vista no representa aislamiento por agente.")).toBeVisible();
});
