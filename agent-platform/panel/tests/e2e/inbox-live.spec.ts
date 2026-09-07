import { expect, type Page, test } from "@playwright/test";

const AGENT = "00000000-0000-0000-0000-0000000000a1";
const CHAT = "20000000-0000-0000-0000-000000000002";
const ADMIN = "10000000-0000-0000-0000-000000000001";
const permissions = ["conversations.read", "conversations.manage"];
const user = {
  id: ADMIN,
  name: "Operador de prueba",
  email: "operator@example.test",
  permissions,
  is_active: true,
  role: "operator",
};
const initialSnapshot = {
  revision: "initial",
  unread_conversations: 1,
  active_conversations: 1,
  historical_conversations: 2,
};
function message(index: number, role = "user", origin: string | null = null) {
  return {
    id: `30000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
    role,
    content: `Mensaje de prueba ${index}`,
    status: "completed",
    origin,
    actor_admin_id: origin === "operator" ? ADMIN : null,
    tool_names: [],
    created_at: new Date(1_783_000_000_000 + index * 1_000).toISOString(),
  };
}
function conversation() {
  return {
    id: CHAT,
    principal_id: "visitor-test",
    display_name: "Consulta en vivo",
    channel: "web",
    route_key: "website",
    status: "active",
    control_mode: "human",
    control_version: 2,
    routing_agent: { id: AGENT, name: "Comercial" },
    automation_agent: { id: AGENT, name: "Comercial" },
    automation_version: 1,
    assigned_operator: user,
    control_changed_at: "2026-09-07T10:00:00Z",
    control_reason: null,
    message_count: 1,
    last_activity_at: "2026-09-07T10:00:00Z",
    owner_agent_id: AGENT,
    owner_agent_name: "Comercial",
    capabilities: permissions,
    unread_count: 1,
    latest_inbound_message_id: message(1).id,
    agent_activity: null as null | { status: string; agent_id: string; name: string },
  };
}
async function fixture(page: Page, count = 1, rejectInitialToken = false) {
  const state = {
    row: conversation(),
    messages: Array.from({ length: count }, (_, index) => message(index + 1)),
    reads: [] as string[][],
    lifecycle: [] as string[],
    listRequests: 0,
    refreshCalls: 0,
  };
  await page.addInitScript(
    ({ initialSnapshot, rejectInitialToken }) => {
      localStorage.setItem(
        "tokens",
        JSON.stringify({ access_token: "private-test-token", refresh_token: "test-refresh" }),
      );
      const original = window.fetch.bind(window);
      Object.assign(window, { __streamRequests: [] });
      window.fetch = async (input, init) => {
        if (!String(input).endsWith("/api/admin/crm/inbox/live")) return original(input, init);
        (window as unknown as { __streamRequests: unknown[] }).__streamRequests.push({
          url: String(input),
          authorization: new Headers(init?.headers).get("Authorization"),
        });
        if (
          rejectInitialToken &&
          new Headers(init?.headers).get("Authorization") === "Bearer private-test-token"
        )
          return new Response(JSON.stringify({ detail: "Expired" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          });
        const encoder = new TextEncoder();
        let controller: ReadableStreamDefaultController<Uint8Array>;
        const body = new ReadableStream<Uint8Array>({
          start(value) {
            controller = value;
          },
        });
        const emit = (snapshot: unknown) =>
          controller.enqueue(
            encoder.encode(`event: inbox.snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`),
          );
        Object.assign(window, { __inboxPush: emit, __inboxEnd: () => controller.close() });
        init?.signal?.addEventListener("abort", () => controller.close(), { once: true });
        emit(initialSnapshot);
        return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
      };
    },
    { initialSnapshot, rejectInitialToken },
  );
  await page.route("**/api/admin/**", async (route) => {
    const url = new URL(route.request().url());
    const reply = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.endsWith("/auth/me")) return reply(user);
    if (url.pathname.endsWith("/auth/refresh")) {
      state.refreshCalls++;
      return reply({ access_token: "renewed-token", refresh_token: "renewed-refresh" });
    }
    if (url.pathname.endsWith("/crm/inbox/agents"))
      return reply([{ id: AGENT, name: "Comercial", is_active: true, capabilities: permissions }]);
    if (url.pathname.endsWith("/crm/inbox")) {
      state.listRequests++;
      state.lifecycle.push(url.searchParams.get("lifecycle") || "");
      return reply({ items: [state.row], total: 1, limit: 50, offset: 0 });
    }
    if (url.pathname.endsWith("/inbox/operators")) return reply([user]);
    if (url.pathname.endsWith(`/inbox/${CHAT}`))
      return reply({ conversation: state.row, messages: state.messages, control_events: [] });
    if (url.pathname.endsWith(`/inbox/${CHAT}/read`)) {
      state.reads.push(route.request().postDataJSON().message_ids);
      state.row.unread_count = 0;
      return reply({ unread_count: 0 });
    }
    return reply({ detail: "Unexpected request" }, 404);
  });
  return state;
}
async function push(page: Page, revision: string, unread = 1) {
  await page.evaluate(
    (snapshot) =>
      (window as unknown as { __inboxPush: (snapshot: unknown) => void }).__inboxPush(snapshot),
    { ...initialSnapshot, revision, unread_conversations: unread },
  );
}

test("live inbox updates without manual refresh, keeps draft and labels both response authors", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const state = await fixture(page);
  await page.goto("/inbox");
  await expect(page.getByText("Actualización en tiempo real", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("status", { name: "1 conversaciones activas sin leer", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const draft = page.getByLabel("Respuesta del operador");
  await draft.fill("Conservo esta respuesta sin enviar");
  state.messages.push(message(2, "assistant", "operator"), message(3, "assistant"));
  state.row.message_count = 3;
  await push(page, "new-message");
  await expect(page.getByText("Mensaje de prueba 3", { exact: true })).toBeVisible();
  await expect(draft).toHaveValue("Conservo esta respuesta sin enviar");
  await expect(draft).toBeFocused();
  const log = page.getByRole("log");
  await expect(log.getByText("Operador", { exact: true })).toHaveClass(/text-amber-300/);
  await expect(log.getByText("Agente", { exact: true })).toHaveClass(/text-amber-300/);
  await expect.poll(() => state.reads.length).toBeGreaterThan(0);
  expect(
    state.reads
      .flat()
      .every((id) => state.messages.some((item) => item.id === id && item.role === "user")),
  ).toBe(true);
  const requests = await page.evaluate(
    () =>
      (window as unknown as { __streamRequests: { url: string; authorization: string }[] })
        .__streamRequests,
  );
  expect(requests[0].authorization).toBe("Bearer private-test-token");
  expect(requests[0].url).not.toContain("token");
  await push(page, "read", 0);
  await expect(page.getByRole("status", { name: /conversaciones activas sin leer/ })).toHaveCount(
    0,
  );
});

test("active and historical views are server filters, not inferred online presence", async ({
  page,
}) => {
  const state = await fixture(page);
  await page.goto("/inbox");
  await page.getByRole("button", { name: "Históricas (2)", exact: true }).click();
  await expect.poll(() => state.lifecycle.at(-1)).toBe("history");
  await page.getByRole("button", { name: "Activas (1)", exact: true }).click();
  await expect.poll(() => state.lifecycle.at(-1)).toBe("active");
  await expect(page.getByText(/no personas conectadas/)).toBeVisible();
  expect(state.reads).toHaveLength(0);
});

test("scrolled reading remains in place and unread until visitor messages are actually observed", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const state = await fixture(page, 80);
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const log = page.getByRole("log");
  await log.scrollIntoViewIfNeeded();
  await expect.poll(() => state.reads.length).toBeGreaterThan(0);
  await log.evaluate((element) => {
    element.scrollTop = 0;
    element.dispatchEvent(new Event("scroll"));
  });
  const readCount = state.reads.length;
  state.messages.push(message(81));
  state.row.unread_count = 1;
  await push(page, "off-bottom");
  await expect(page.getByRole("button", { name: "Ver mensajes nuevos ↓" })).toBeVisible();
  expect(await log.evaluate((element) => element.scrollTop)).toBe(0);
  expect(state.reads).toHaveLength(readCount);
  await page.getByRole("button", { name: "Ver mensajes nuevos ↓" }).click();
  await expect.poll(() => state.reads.length).toBeGreaterThan(readCount);
  expect(state.reads.at(-1)).toContain(message(81).id);
});

test("hidden tab never acknowledges messages and reconnects when visible", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/inbox");
  await expect(page.getByText("Actualización en tiempo real", { exact: true })).toBeVisible();
  const before = await page.evaluate(
    () => (window as unknown as { __streamRequests: unknown[] }).__streamRequests.length,
  );
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(page.getByText("Mensaje de prueba 1", { exact: true })).toBeVisible();
  expect(state.reads).toHaveLength(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect
    .poll(async () =>
      page.evaluate(
        () => (window as unknown as { __streamRequests: unknown[] }).__streamRequests.length,
      ),
    )
    .toBe(before + 1);
});

test("queued and preparing states reflect backend activity and disappear for human control", async ({
  page,
}) => {
  const state = await fixture(page);
  state.row.control_mode = "automated";
  state.row.assigned_operator = null as unknown as typeof user;
  state.row.agent_activity = { status: "queued", agent_id: AGENT, name: "Comercial" };
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Comercial: respuesta en cola…" }),
  ).toBeVisible();
  state.row.agent_activity.status = "running";
  await push(page, "running");
  await expect(
    page.getByRole("status").filter({ hasText: "Comercial está preparando una respuesta…" }),
  ).toBeVisible();
  state.row.control_mode = "human";
  await push(page, "human");
  await expect(page.getByText("Comercial está preparando una respuesta…")).toHaveCount(0);
});

test("mobile navigation preserves unread badge and composer remains icon-labeled without overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page);
  await page.goto("/inbox");
  await page.getByRole("button", { name: "Abrir navegación" }).click();
  await expect(
    page.getByRole("status", { name: "1 conversaciones activas sin leer", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Abrir navegación" })).toBeFocused();
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(page.getByRole("button", { name: "Enviar respuesta" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test("live stream refreshes expired bearer credentials without putting them in its URL", async ({
  page,
}) => {
  const state = await fixture(page, 1, true);
  await page.goto("/inbox");
  await expect(page.getByText("Actualización en tiempo real", { exact: true })).toBeVisible();
  expect(state.refreshCalls).toBe(1);
  const requests = await page.evaluate(
    () =>
      (window as unknown as { __streamRequests: { url: string; authorization: string }[] })
        .__streamRequests,
  );
  expect(requests.some((request) => request.authorization === "Bearer renewed-token")).toBe(true);
  expect(requests.every((request) => !request.url.includes("token"))).toBe(true);
});

test("disconnected typing is hidden and an unchanged reconnect snapshot still refreshes authoritative state", async ({
  page,
}) => {
  const state = await fixture(page);
  state.row.control_mode = "automated";
  state.row.assigned_operator = null as unknown as typeof user;
  state.row.agent_activity = { status: "running", agent_id: AGENT, name: "Comercial" };
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Comercial está preparando una respuesta…" }),
  ).toBeVisible();
  const requests = state.listRequests;
  state.row.agent_activity = null;
  await page.evaluate(() => (window as unknown as { __inboxEnd: () => void }).__inboxEnd());
  await expect(
    page.getByRole("status").filter({ hasText: "Comercial está preparando una respuesta…" }),
  ).toHaveCount(0);
  await expect(page.getByText("Agente preparando respuesta…", { exact: true })).toHaveCount(0);
  await expect.poll(() => state.listRequests).toBeGreaterThan(requests);
  await expect(page.getByText("Actualización en tiempo real", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "Comercial está preparando una respuesta…" }),
  ).toHaveCount(0);
});

test("new visible inbound during an in-flight read is acknowledged without hiding it behind a stale count", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const state = await fixture(page);
  let releaseFirstRead = () => {};
  const firstRead = new Promise<void>((resolve) => {
    releaseFirstRead = resolve;
  });
  await page.route(`**/api/admin/agents/${AGENT}/inbox/${CHAT}/read`, async (route) => {
    const ids = route.request().postDataJSON().message_ids as string[];
    state.reads.push(ids);
    if (state.reads.length === 1) await firstRead;
    else state.row.unread_count = 0;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ unread_count: 0 }),
    });
  });
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await page.getByRole("log").scrollIntoViewIfNeeded();
  await expect.poll(() => state.reads.length).toBe(1);
  state.messages.push(message(2));
  state.row.unread_count = 2;
  state.row.latest_inbound_message_id = message(2).id;
  await push(page, "inbound-during-read");
  await expect(page.getByText("Mensaje de prueba 2", { exact: true })).toBeVisible();
  releaseFirstRead();
  await expect.poll(() => state.reads.length).toBe(2);
  expect(state.reads).toEqual([[message(1).id], [message(2).id]]);
});
