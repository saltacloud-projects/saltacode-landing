import { expect, test } from "@playwright/test";
import { AGENT, CHAT, fixture, push } from "./fixtures/inbox";

const browserNow = "2026-09-07T17:00:00Z";
const expiry = "2026-09-07T17:00:08Z";

test("operator editing publishes throttled booleans with an instance sequence, never draft text", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(browserNow) });
  const state = await fixture(page);
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const draft = page.getByLabel("Respuesta del operador");
  await draft.focus();
  expect(state.presenceSignals).toHaveLength(0);
  await draft.fill("Mensaje privado que no se transmite en presencia");
  await expect.poll(() => state.presenceSignals.length).toBe(1);
  await draft.pressSequentially("...", { delay: 10 });
  expect(state.presenceSignals).toHaveLength(1);
  await page.clock.fastForward(3_100);
  await draft.pressSequentially(" continuando");
  await expect.poll(() => state.presenceSignals.length).toBe(2);
  expect(state.presenceSignals[0]).toEqual({
    client_instance_id: expect.stringMatching(
      /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i,
    ),
    sequence: 1,
    typing: true,
    expected_control_version: 2,
  });
  expect(state.presenceSignals[1]).toEqual({ ...state.presenceSignals[0], sequence: 2 });
  await page.clock.fastForward(8_100);
  await expect.poll(() => state.presenceSignals.length).toBe(3);
  expect(state.presenceSignals[2]).toEqual({
    ...state.presenceSignals[0],
    sequence: 3,
    typing: false,
  });
  await expect(draft).toHaveValue(/Mensaje privado/);
  expect(state.presenceSignals.filter((signal) => signal.typing)).toHaveLength(2);
});

test("blur, hidden tab, conversation exit and reply submission clear operator typing", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await fixture(page);
  await page.route(`**/api/admin/agents/${AGENT}/inbox/${CHAT}/operator-messages`, (route) =>
    route.fulfill({ contentType: "application/json", body: "{}", status: 202 }),
  );
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const draft = page.getByLabel("Respuesta del operador");
  await draft.fill("Primera edición");
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(true);
  await page.getByRole("button", { name: "Detalles y controles" }).focus();
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(false);
  await draft.fill("Segunda edición");
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(true);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(false);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const stopped = state.presenceSignals.length;
  await expect(draft).toHaveValue("Segunda edición");
  expect(state.presenceSignals.length).toBe(stopped);
  await draft.fill("Tercera edición");
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(true);
  await page.getByRole("button", { name: "Volver a conversaciones" }).click();
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(false);
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await draft.fill("Respuesta final");
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(true);
  await draft.press("Enter");
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(false);
  await expect(draft).toHaveValue("");
  expect(state.presenceSignals.every((signal, index) => signal.sequence === index + 1)).toBe(true);
});

test("typing errors never block the composer and a stale ownership epoch is not retried", async ({
  page,
}) => {
  const state = await fixture(page);
  await page.route(`**/api/admin/agents/${AGENT}/inbox/${CHAT}/presence`, async (route) => {
    state.presenceSignals.push(route.request().postDataJSON());
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: '{"detail":"Changed ownership"}',
    });
  });
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const draft = page.getByLabel("Respuesta del operador");
  await draft.fill("Borrador local");
  await expect.poll(() => state.presenceSignals.length).toBe(1);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await draft.fill("Borrador local conservado");
  expect(state.presenceSignals.filter((signal) => signal.typing)).toHaveLength(1);
  state.row.control_mode = "paused";
  state.row.control_version = 3;
  await push(page, "ownership-changed");
  await expect(draft).toHaveCount(0);
  expect(state.presenceSignals.filter((signal) => signal.typing)).toHaveLength(1);
});

test("real visitor typing is visible during human control and expires locally without changing unread", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(browserNow) });
  const state = await fixture(page);
  state.row.presence.visitor = { typing: true, expires_at: expiry };
  await page.goto("/inbox");
  await expect(page.getByText("Visitante escribiendo…", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Visitante está escribiendo…" }),
  ).toBeVisible();
  await expect(page.getByText(/preparando una respuesta/)).toHaveCount(0);
  await page.clock.fastForward(8_100);
  await expect(page.getByText("Visitante está escribiendo…", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Visitante escribiendo…", { exact: true })).toHaveCount(0);
  expect(state.presenceSignals).toHaveLength(0);
});

test("human typing hides on disconnect and closed state; another operator is not mistaken for agent activity", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(browserNow) });
  const state = await fixture(page);
  state.row.assigned_operator = { ...state.row.assigned_operator, id: "another-admin" };
  state.row.presence.operator = { typing: true, expires_at: expiry };
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(page.getByText("Operador está escribiendo…", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Respuesta del operador")).toHaveCount(0);
  await page.evaluate(() => (window as unknown as { __inboxEnd: () => void }).__inboxEnd());
  await expect(page.getByText("Operador está escribiendo…", { exact: true })).toHaveCount(0);
  state.row.control_mode = "closed";
  state.row.status = "closed";
  await page.clock.fastForward(1_200);
  await expect(
    page.getByRole("status", { name: "Actualización en tiempo real", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Operador está escribiendo…", { exact: true })).toHaveCount(0);
  expect(state.presenceSignals).toHaveLength(0);
});

test("LAN review without randomUUID still opens the Inbox and emits a valid presence instance", async ({
  page,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined }),
  );
  const state = await fixture(page);
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await page.getByLabel("Respuesta del operador").fill("Edición local");
  await expect.poll(() => state.presenceSignals.length).toBe(1);
  expect(state.presenceSignals[0].client_instance_id).toMatch(
    /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i,
  );
});

test("visitor typing while reading older messages does not claim a new message or acknowledge unread", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(browserNow) });
  const state = await fixture(page, 80);
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect.poll(() => state.reads.length).toBeGreaterThan(0);
  const log = page.getByRole("log");
  await log.evaluate((element) => {
    element.scrollTop = 0;
    element.dispatchEvent(new Event("scroll"));
  });
  const readCount = state.reads.length;
  state.row.presence.visitor = { typing: true, expires_at: expiry };
  await push(page, "typing-only", 0);
  await expect(page.getByText("Visitante escribiendo…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Ver mensajes nuevos ↓" })).toHaveCount(0);
  expect(await log.evaluate((element) => element.scrollTop)).toBe(0);
  expect(state.reads).toHaveLength(readCount);
});

test("presence overflow hides only human signals and resumes from a fresh snapshot without changing AI or unread", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(browserNow) });
  const state = await fixture(page);
  state.row.control_mode = "automated";
  state.row.presence.visitor = { typing: true, expires_at: expiry };
  state.row.agent_activity = { status: "running", agent_id: AGENT, name: "Comercial" };
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(page.getByText("Visitante está escribiendo…", { exact: true })).toBeVisible();
  const ai = page
    .getByRole("status")
    .filter({ hasText: "Comercial está preparando una respuesta…" });
  await expect(ai).toBeVisible();
  const snapshot = {
    revision: "same-server-revision",
    unread_conversations: 1,
    active_conversations: 1,
    historical_conversations: 2,
  };
  for (const degraded of [true, false]) {
    const requests = state.listRequests;
    await page.evaluate(
      (payload) =>
        (window as unknown as { __inboxPush: (value: unknown) => void }).__inboxPush(payload),
      { ...snapshot, presence_degraded: degraded },
    );
    await expect.poll(() => state.listRequests).toBeGreaterThan(requests);
    if (degraded) {
      await expect(page.getByText("Visitante está escribiendo…", { exact: true })).toHaveCount(0);
      await expect(page.getByText("Visitante escribiendo…", { exact: true })).toHaveCount(0);
    } else {
      await expect(page.getByText("Visitante está escribiendo…", { exact: true })).toBeVisible();
    }
    await expect(ai).toBeVisible();
    await expect(
      page.getByRole("status", { name: "1 conversaciones activas sin leer", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Mensaje de prueba 1", { exact: true })).toBeVisible();
  }
  await page.clock.fastForward(8_100);
  await expect(page.getByText("Visitante está escribiendo…", { exact: true })).toHaveCount(0);
  await expect(ai).toBeVisible();
});

test("degraded presence hides other-operator typing without disabling owned human replies", async ({
  page,
}) => {
  await page.clock.install({ time: new Date(browserNow) });
  const state = await fixture(page);
  state.row.assigned_operator = { ...state.row.assigned_operator, id: "other-admin" };
  state.row.presence.operator = { typing: true, expires_at: expiry };
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(page.getByText("Operador está escribiendo…", { exact: true })).toBeVisible();
  await page.evaluate(() =>
    (window as unknown as { __inboxPush: (value: unknown) => void }).__inboxPush({
      revision: "overflow",
      unread_conversations: 1,
      active_conversations: 1,
      historical_conversations: 2,
      presence_degraded: true,
    }),
  );
  await expect(page.getByText("Operador está escribiendo…", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Operador escribiendo…", { exact: true })).toHaveCount(0);
  state.row.assigned_operator = {
    ...state.row.assigned_operator,
    id: "10000000-0000-0000-0000-000000000001",
  };
  state.row.control_version = 3;
  await page.evaluate(() =>
    (window as unknown as { __inboxPush: (value: unknown) => void }).__inboxPush({
      revision: "owned-during-overflow",
      unread_conversations: 1,
      active_conversations: 1,
      historical_conversations: 2,
      presence_degraded: true,
    }),
  );
  await page.getByLabel("Respuesta del operador").fill("La respuesta sigue disponible");
  await expect.poll(() => state.presenceSignals.at(-1)?.typing).toBe(true);
  await expect(page.getByRole("button", { name: "Enviar respuesta" })).toBeEnabled();
});
