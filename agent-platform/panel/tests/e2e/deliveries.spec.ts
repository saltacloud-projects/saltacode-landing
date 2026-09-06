import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";
const DELIVERY_ID = "10000000-0000-0000-0000-000000000001";
const CONVERSATION_ID = "20000000-0000-0000-0000-000000000001";

const admin = {
  id: "30000000-0000-0000-0000-000000000001",
  email: "reviewer@example.test",
  name: "Delivery reviewer",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["profiles.read", "deliveries.read"],
};

const profile = {
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
};

const delivery = {
  id: DELIVERY_ID,
  conversation_id: CONVERSATION_ID,
  channel: "whatsapp",
  status: "delivery_unknown",
  kind: "text",
  sender_type: "automation",
  sequence: 1,
  correlation_id: "correlation-safe-1",
  provider_reference: "…123456",
  attempt_count: 1,
  latest_safe_code: "provider_timeout",
  is_fifo_blocking: true,
  blocked_message_count: 2,
  created_at: "2026-09-06T10:00:00Z",
  updated_at: "2026-09-06T10:01:00Z",
};

async function json(route: Route, value: unknown) {
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
}

async function prepare(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "tokens",
      JSON.stringify({ access_token: "test", refresh_token: "test" }),
    );
  });
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith("/deliveries/")) {
      return json(route, { items: [delivery], total: 1, limit: 100, offset: 0 });
    }
    if (path.endsWith(`/deliveries/${DELIVERY_ID}`)) {
      return json(route, {
        ...delivery,
        channel_route_id: "40000000-0000-0000-0000-000000000001",
        chat_message_id: null,
        control_version: 0,
        accepted_at: null,
        delivered_at: null,
        attempts: [
          {
            id: "50000000-0000-0000-0000-000000000001",
            attempt_number: 1,
            control_version: 0,
            created_at: "2026-09-06T10:00:30Z",
          },
        ],
        events: [
          {
            id: "60000000-0000-0000-0000-000000000001",
            attempt_id: "50000000-0000-0000-0000-000000000001",
            event_type: "delivery_unknown",
            from_status: "dispatching",
            to_status: "delivery_unknown",
            actor_type: "worker",
            safe_code: "provider_timeout",
            created_at: "2026-09-06T10:01:00Z",
          },
        ],
      });
    }
    return route.fulfill({ status: 500, body: `Mock missing: ${path}` });
  });
}

test("reviewer sees safe evidence and cannot retry a delivery", async ({ page }) => {
  await prepare(page);
  await page.goto(`/agents/${AGENT_ID}/deliveries`);

  const list = page.getByLabel("Lista de entregas");
  await expect(list.getByText("Entrega incierta")).toBeVisible();
  await expect(list.getByText("provider_timeout")).toBeVisible();
  await list.getByRole("button", { name: /whatsapp.*#1.*1 intento/i }).click();

  const detail = page.getByLabel("Detalle de entrega");
  await expect(detail.getByText("…123456")).toBeVisible();
  await expect(detail.getByText("correlation-safe-1")).toBeVisible();
  await expect(detail.getByText("2 entrega(s) en espera")).toBeVisible();
  await expect(detail.getByText("provider_timeout")).toBeVisible();
  await expect(page.getByRole("button", { name: /reintentar/i })).toHaveCount(0);
  await expect(page.getByText("provider-secret-reference")).toHaveCount(0);
});

test("mobile delivery review has no horizontal overflow", async ({ page }) => {
  await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/agents/${AGENT_ID}/deliveries`);
  await page.getByRole("button", { name: /whatsapp.*#1.*1 intento/i }).click();

  await expect(page.getByRole("button", { name: "Volver a entregas" })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});
