import { expect, test } from "@playwright/test";
import { AGENT, CHAT, fixture, message, push, user } from "./fixtures/inbox";

test("live inbox updates without manual refresh, keeps draft and labels both response authors", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  const state = await fixture(page);
  await page.goto("/inbox");
  await expect(
    page.getByRole("status", { name: "Actualización en tiempo real", exact: true }),
  ).toBeVisible();
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
  await page.getByRole("button", { name: "Historial", exact: true }).click();
  await expect.poll(() => state.lifecycle.at(-1)).toBe("history");
  await page.getByRole("button", { name: "Activas", exact: true }).click();
  await expect.poll(() => state.lifecycle.at(-1)).toBe("active");
  await page.getByText("Filtros y alcance", { exact: true }).click();
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
  await expect(
    page.getByRole("status", { name: "Actualización en tiempo real", exact: true }),
  ).toBeVisible();
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
  await expect(
    page.getByRole("status", { name: "Actualización en tiempo real", exact: true }),
  ).toBeVisible();
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
  await expect(
    page.getByRole("status", { name: "Actualización en tiempo real", exact: true }),
  ).toBeVisible();
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
