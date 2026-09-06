import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_A = "00000000-0000-0000-0000-0000000000a1";
const AGENT_B = "00000000-0000-0000-0000-0000000000b2";
const ADMIN_ID = "10000000-0000-0000-0000-000000000001";
const OTHER_ADMIN_ID = "10000000-0000-0000-0000-000000000002";
const PRINCIPAL_ID = "20000000-0000-0000-0000-000000000001";
const CONVERSATION_ID = "30000000-0000-0000-0000-000000000001";

const admin = {
  id: ADMIN_ID,
  email: "operator@example.test",
  name: "Operator",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: [
    "profiles.read",
    "conversations.read",
    "conversations.manage",
    "runtime.manage",
  ],
};

const profile = (id: string, name: string, slug: string) => ({
  id,
  name,
  slug,
  version: 1,
  is_active: true,
  is_public: true,
  retention_days: 30,
  description: `${name} description`,
  prompt_identity: "Identity",
  prompt_domain: "Domain",
  prompt_guardrails: "Guardrails",
  unauthorized_message: "Unauthorized",
  error_message: "Error",
  created_at: "2026-09-06T10:00:00Z",
  updated_at: "2026-09-06T10:00:00Z",
});

interface InboxState {
  mode: "automated" | "paused" | "human" | "closed";
  version: number;
  ownerId: string | null;
  automationAgentId: string;
  automationVersion: number;
  assignmentHistory: Array<Record<string, unknown>>;
  messages: Array<Record<string, unknown>>;
}

function operator(id: string, name: string) {
  return { id, name, email: `${name.toLowerCase()}@example.test` };
}

function conversation(state: InboxState) {
  const automationAgent =
    state.automationAgentId === AGENT_B
      ? { id: AGENT_B, name: "Agent Beta" }
      : { id: AGENT_A, name: "Agent Alpha" };
  return {
    id: CONVERSATION_ID,
    principal_id: PRINCIPAL_ID,
    display_name: "Lead web",
    channel: "web",
    route_key: "saltacode-landing",
    status: "active",
    control_mode: state.mode,
    control_version: state.version,
    routing_agent: { id: AGENT_A, name: "Agent Alpha" },
    automation_agent: automationAgent,
    automation_version: state.automationVersion,
    assigned_operator:
      state.ownerId === ADMIN_ID
        ? operator(ADMIN_ID, "Operator")
        : state.ownerId === OTHER_ADMIN_ID
          ? operator(OTHER_ADMIN_ID, "Partner")
          : null,
    control_changed_at: "2026-09-06T10:00:00Z",
    control_reason: null,
    message_count: state.messages.length,
    last_activity_at: "2026-09-06T10:00:00Z",
  };
}

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function prepare(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem(
      "tokens",
      JSON.stringify({ access_token: "test", refresh_token: "test" }),
    );
  });
}

function registerInboxMocks(
  page: Page,
  state: InboxState,
  onTransition?: (route: Route, body: Record<string, unknown>) => Promise<void>,
  onMessage?: (route: Route, body: Record<string, unknown>) => Promise<void>,
  onAutomationAssignment?: (
    route: Route,
    body: Record<string, unknown>,
  ) => Promise<void>,
) {
  return page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/profiles/")) {
      return json(route, [
        profile(AGENT_A, "Agent Alpha", "alpha"),
        profile(AGENT_B, "Agent Beta", "beta"),
      ]);
    }
    if (path.endsWith("/inbox/operators")) {
      return json(route, [operator(ADMIN_ID, "Operator"), operator(OTHER_ADMIN_ID, "Partner")]);
    }
    if (path.endsWith("/inbox/") && request.method() === "GET") {
      const requestedAgent = path.split("/").at(-3);
      return json(route, {
        items: requestedAgent === AGENT_A ? [conversation(state)] : [],
        total: requestedAgent === AGENT_A ? 1 : 0,
        limit: 100,
        offset: 0,
      });
    }
    if (path.endsWith(`/inbox/${CONVERSATION_ID}`) && request.method() === "GET") {
      return json(route, {
        conversation: conversation(state),
        messages: state.messages,
        control_events: [],
      });
    }
    if (
      path.endsWith(`/inbox/${CONVERSATION_ID}/automation-assignments`) &&
      request.method() === "GET"
    ) {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 10);
      return json(route, {
        items: state.assignmentHistory.slice(offset, offset + limit),
        total: state.assignmentHistory.length,
        limit,
        offset,
      });
    }
    if (
      path.endsWith(`/inbox/${CONVERSATION_ID}/automation-assignments`) &&
      request.method() === "POST"
    ) {
      const body = request.postDataJSON();
      if (onAutomationAssignment) return onAutomationAssignment(route, body);
      const previousAgent =
        state.automationAgentId === AGENT_B
          ? { id: AGENT_B, name: "Agent Beta" }
          : { id: AGENT_A, name: "Agent Alpha" };
      state.automationAgentId = String(body.target_agent_id);
      state.automationVersion += 1;
      const nextAgent =
        state.automationAgentId === AGENT_B
          ? { id: AGENT_B, name: "Agent Beta" }
          : { id: AGENT_A, name: "Agent Alpha" };
      state.assignmentHistory.unshift({
        event_id: "assignment-event",
        from_automation_agent: previousAgent,
        to_automation_agent: nextAgent,
        automation_version: state.automationVersion,
        applied: true,
        trigger: body.trigger,
        actor_admin_id: ADMIN_ID,
        reason: body.reason,
        created_at: "2026-09-06T10:03:00Z",
      });
      return json(route, {
        event_id: "assignment-event",
        applied: true,
        duplicate: false,
        automation_agent_id: state.automationAgentId,
        automation_version: state.automationVersion,
      });
    }
    if (path.endsWith(`/inbox/${CONVERSATION_ID}/control-transitions`)) {
      const body = request.postDataJSON();
      if (onTransition) return onTransition(route, body);
      state.mode = body.target_mode;
      state.version += 1;
      state.ownerId = body.target_mode === "human" ? body.assigned_admin_id : null;
      return json(route, {
        conversation_id: CONVERSATION_ID,
        agent_id: AGENT_A,
        mode: state.mode,
        version: state.version,
        assigned_admin_id: state.ownerId,
        changed_at: "2026-09-06T10:01:00Z",
        reason: body.reason ?? null,
      });
    }
    if (path.endsWith(`/inbox/${CONVERSATION_ID}/operator-messages`)) {
      const body = request.postDataJSON();
      if (onMessage) return onMessage(route, body);
      state.messages.push({
        id: "message-operator",
        role: "assistant",
        content: body.content,
        status: "completed",
        tool_names: [],
        origin: "operator",
        actor_admin_id: ADMIN_ID,
        created_at: "2026-09-06T10:02:00Z",
      });
      return json(
        route,
        {
          message_id: "message-operator",
          delivery_status: "published",
          control: {},
        },
        202,
      );
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

test("operator takes control and responds with the current ownership version", async ({ page }) => {
  await prepare(page);
  const state: InboxState = {
    mode: "automated",
    version: 0,
    ownerId: null,
    automationAgentId: AGENT_A,
    automationVersion: 0,
    assignmentHistory: [],
    messages: [
      {
        id: "message-user",
        role: "user",
        content: "Necesito una web para mi empresa",
        status: "completed",
        tool_names: [],
        origin: "channel",
        actor_admin_id: null,
        created_at: "2026-09-06T10:00:00Z",
      },
    ],
  };
  const transitions: Record<string, unknown>[] = [];
  const messages: Array<{ body: Record<string, unknown>; key: string | undefined }> = [];
  await registerInboxMocks(
    page,
    state,
    async (route, body) => {
      transitions.push(body);
      state.mode = "human";
      state.version = 1;
      state.ownerId = ADMIN_ID;
      await json(route, {});
    },
    async (route, body) => {
      messages.push({ body, key: route.request().headers()["idempotency-key"] });
      state.messages.push({
        id: "message-operator",
        role: "assistant",
        content: body.content,
        status: "completed",
        tool_names: [],
        origin: "operator",
        actor_admin_id: ADMIN_ID,
        created_at: "2026-09-06T10:02:00Z",
      });
      await json(route, {}, 202);
    },
  );

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();
  await expect(page.getByText("Necesito una web para mi empresa")).toBeVisible();
  await expect(page.getByRole("button", { name: "Eliminar" })).toHaveCount(0);
  await page.getByRole("button", { name: "Tomar control" }).click();
  await expect.poll(() => transitions).toHaveLength(1);
  expect(transitions[0]).toMatchObject({
    target_mode: "human",
    expected_version: 0,
    assigned_admin_id: ADMIN_ID,
  });

  await page.getByLabel("Respuesta del operador").fill("Coordinemos el alcance.");
  await page.getByRole("button", { name: "Enviar" }).click();
  await expect.poll(() => messages).toHaveLength(1);
  expect(messages[0].body).toEqual({
    content: "Coordinemos el alcance.",
    expected_version: 1,
  });
  expect(messages[0].key).toMatch(/^operator-/);
  await expect(page.getByText("Coordinemos el alcance.")).toBeVisible();

  await page.getByLabel("Agente de trabajo").selectOption(AGENT_B);
  await expect(page).toHaveURL(new RegExp(`/agents/${AGENT_B}/inbox$`));
  await expect(page.getByText("No hay conversaciones para estos filtros.")).toBeVisible();
});

test("a stale control command refreshes the thread and disables the composer", async ({
  page,
}) => {
  await prepare(page);
  const state: InboxState = {
    mode: "human",
    version: 3,
    ownerId: ADMIN_ID,
    automationAgentId: AGENT_A,
    automationVersion: 0,
    assignmentHistory: [],
    messages: [],
  };
  let attempts = 0;
  await registerInboxMocks(page, state, async (route) => {
    attempts += 1;
    state.mode = "paused";
    state.version = 4;
    state.ownerId = ADMIN_ID;
    await json(route, { detail: "control version changed" }, 409);
  });

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();
  await expect(page.getByLabel("Respuesta del operador")).toBeVisible();
  await page.getByRole("button", { name: "Pausar" }).click();

  await expect.poll(() => attempts).toBe(1);
  await expect(page.getByRole("alert")).toContainText("Actualizamos el estado");
  await expect(
    page.getByLabel("Detalle de conversación").getByText("Pausado", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Respuesta del operador")).toHaveCount(0);
});

test("operator prepares a different acting agent without resuming a paused conversation", async ({
  page,
}) => {
  await prepare(page);
  const state: InboxState = {
    mode: "paused",
    version: 4,
    ownerId: ADMIN_ID,
    automationAgentId: AGENT_A,
    automationVersion: 0,
    assignmentHistory: [],
    messages: [],
  };
  const assignments: Array<{
    body: Record<string, unknown>;
    idempotencyKey?: string;
    correlationId?: string;
  }> = [];
  await registerInboxMocks(page, state, undefined, undefined, async (route, body) => {
    assignments.push({
      body,
      idempotencyKey: route.request().headers()["idempotency-key"],
      correlationId: route.request().headers()["x-correlation-id"],
    });
    const previousAgent = { id: AGENT_A, name: "Agent Alpha" };
    state.automationAgentId = AGENT_B;
    state.automationVersion = 1;
    state.assignmentHistory = [
      {
        event_id: "assignment-event",
        from_automation_agent: previousAgent,
        to_automation_agent: { id: AGENT_B, name: "Agent Beta" },
        automation_version: 1,
        applied: true,
        trigger: body.trigger,
        actor_admin_id: ADMIN_ID,
        reason: body.reason,
        created_at: "2026-09-06T10:03:00Z",
      },
    ];
    await json(route, {
      event_id: "assignment-event",
      applied: true,
      duplicate: false,
      automation_agent_id: AGENT_B,
      automation_version: 1,
    });
  });

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();

  await expect(page.getByText("Canal / agente de routing")).toBeVisible();
  await expect(page.getByText("Responde automáticamente", { exact: true })).toBeVisible();
  await page.getByLabel("Agente que responde automáticamente").selectOption(AGENT_B);
  await page.getByRole("button", { name: "Asignar respuesta automática" }).click();

  await expect.poll(() => assignments).toHaveLength(1);
  expect(assignments[0].body).toEqual({
    target_agent_id: AGENT_B,
    expected_automation_version: 0,
    trigger: "operator_reassignment",
    reason: "Assigned from operator inbox",
  });
  expect(assignments[0].idempotencyKey).toMatch(/^automation-assignment-/);
  expect(assignments[0].correlationId).toMatch(/^inbox-correlation-/);
  expect(assignments[0].idempotencyKey).not.toBe(assignments[0].correlationId);
  await expect(page.getByRole("status")).toContainText("la automatización sigue detenida");
  await expect(
    page.getByLabel("Detalle de conversación").getByText("Pausado", { exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Ver historial" }).click();
  await expect(page.getByText("Agent Alpha → Agent Beta")).toBeVisible();
  await expect(page.locator("#automation-assignment-history").getByText(/Versión 1/)).toBeVisible();
});

test("acting-agent history loads on demand and paginates without exposing event ids", async ({
  page,
}) => {
  await prepare(page);
  const state: InboxState = {
    mode: "automated",
    version: 0,
    ownerId: null,
    automationAgentId: AGENT_A,
    automationVersion: 11,
    assignmentHistory: Array.from({ length: 11 }, (_, index) => ({
      event_id: `private-event-${index + 1}`,
      from_automation_agent: { id: AGENT_A, name: "Agent Alpha" },
      to_automation_agent: { id: AGENT_B, name: "Agent Beta" },
      automation_version: 11 - index,
      applied: true,
      trigger: "operator_reassignment",
      actor_admin_id: ADMIN_ID,
      reason: `Cambio auditado ${index + 1}`,
      created_at: `2026-09-06T10:${String(index).padStart(2, "0")}:00Z`,
    })),
    messages: [],
  };
  const historyOffsets: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      request.method() === "GET" &&
      url.pathname.endsWith(`/inbox/${CONVERSATION_ID}/automation-assignments`)
    ) {
      historyOffsets.push(url.searchParams.get("offset") ?? "");
    }
  });
  await registerInboxMocks(page, state);

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();
  expect(historyOffsets).toEqual([]);

  await page.getByRole("button", { name: "Ver historial" }).click();
  await expect.poll(() => historyOffsets).toEqual(["0"]);
  await expect(page.getByText("Cambio auditado 10")).toBeVisible();
  await expect(page.getByText("Cambio auditado 11")).toHaveCount(0);
  await expect(page.getByText(/private-event-/)).toHaveCount(0);

  await page.getByRole("button", { name: "Cargar más" }).click();
  await expect.poll(() => historyOffsets).toEqual(["0", "10"]);
  await expect(page.getByText("Cambio auditado 11")).toBeVisible();
});

test("a stale acting-agent assignment refreshes its independent version", async ({ page }) => {
  await prepare(page);
  const state: InboxState = {
    mode: "human",
    version: 7,
    ownerId: ADMIN_ID,
    automationAgentId: AGENT_A,
    automationVersion: 2,
    assignmentHistory: [],
    messages: [],
  };
  let attempts = 0;
  await registerInboxMocks(page, state, undefined, undefined, async (route) => {
    attempts += 1;
    state.automationAgentId = AGENT_B;
    state.automationVersion = 3;
    await json(route, { detail: "automation version changed" }, 409);
  });

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();
  await page.getByLabel("Agente que responde automáticamente").selectOption(AGENT_B);
  await page.getByRole("button", { name: "Asignar respuesta automática" }).click();

  await expect.poll(() => attempts).toBe(1);
  await expect(page.getByRole("alert")).toContainText("Actualizamos el agente automático");
  await expect(
    page.getByRole("definition").filter({ hasText: /^Agent Beta$/ }),
  ).toBeVisible();
  await expect(page.getByText("Versión 3", { exact: true })).toBeVisible();
  await expect(
    page.getByLabel("Detalle de conversación").getByText("Atención manual", { exact: true }),
  ).toBeVisible();
});

test("an unavailable acting-agent target is reported without enumerating it", async ({ page }) => {
  await prepare(page);
  const state: InboxState = {
    mode: "automated",
    version: 0,
    ownerId: null,
    automationAgentId: AGENT_A,
    automationVersion: 0,
    assignmentHistory: [],
    messages: [],
  };
  await registerInboxMocks(page, state, undefined, undefined, async (route) => {
    await json(route, { detail: "Conversation or agent not found" }, 404);
  });

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();
  await page.getByLabel("Agente que responde automáticamente").selectOption(AGENT_B);
  await page.getByRole("button", { name: "Asignar respuesta automática" }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toContainText("permisos disponibles");
  await expect(alert).not.toContainText("Agent Beta");
});

test("closed conversations expose acting-agent history but disable reassignment", async ({ page }) => {
  await prepare(page);
  const state: InboxState = {
    mode: "closed",
    version: 9,
    ownerId: null,
    automationAgentId: AGENT_A,
    automationVersion: 2,
    assignmentHistory: [],
    messages: [],
  };
  await registerInboxMocks(page, state);

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();

  await expect(page.getByLabel("Agente que responde automáticamente")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Asignar respuesta automática" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Ver historial" })).toBeEnabled();
});

test("mobile inbox opens one thread without horizontal overflow", async ({ page }) => {
  await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const state: InboxState = {
    mode: "automated",
    version: 0,
    ownerId: null,
    automationAgentId: AGENT_A,
    automationVersion: 0,
    assignmentHistory: [],
    messages: [],
  };
  await registerInboxMocks(page, state);

  await page.goto(`/agents/${AGENT_A}/inbox`);
  await page.getByRole("button", { name: /Lead web/ }).click();
  await expect(page.getByRole("button", { name: "Volver a conversaciones" })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
  await page.getByRole("button", { name: "Volver a conversaciones" }).click();
  await expect(page.getByRole("button", { name: /Lead web/ })).toBeVisible();
});
