import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";
const ADMIN_ID = "10000000-0000-0000-0000-000000000001";
const OPPORTUNITY_ID = "20000000-0000-0000-0000-000000000001";
const MEETING_ID = "30000000-0000-0000-0000-000000000001";
const SLOT_ID = "40000000-0000-0000-0000-000000000001";

const admin = {
  id: ADMIN_ID,
  email: "operator@example.test",
  name: "Operator",
  role: "admin",
  is_active: true,
  must_change_password: false,
  permissions: ["*"],
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

interface MeetingState {
  status: string;
  stateVersion: number;
  proposalVersion: number;
  selectedSlotId: string | null;
  conflictNext: boolean;
}

interface RecordedCommand {
  path: string;
  body: Record<string, unknown>;
  idempotencyKey?: string;
  correlationId?: string;
}

function slot() {
  return {
    id: SLOT_ID,
    proposal_version: 1,
    position: 1,
    starts_at: "2026-09-10T13:00:00Z",
    ends_at: "2026-09-10T14:00:00Z",
    timezone: "America/Argentina/Salta",
    created_at: "2026-09-06T10:01:00Z",
  };
}

function summary(state: MeetingState) {
  return {
    id: MEETING_ID,
    opportunity_id: OPPORTUNITY_ID,
    conversation_id: null,
    status: state.status,
    state_version: state.stateVersion,
    proposal_version: state.proposalVersion,
    selected_slot_id: state.selectedSlotId,
    selected_slot: state.selectedSlotId ? slot() : null,
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:05:00Z",
  };
}

function detail(state: MeetingState) {
  return {
    ...summary(state),
    slots: [slot()],
    events: [
      {
        id: "50000000-0000-0000-0000-000000000001",
        event_type: "created",
        from_status: null,
        to_status: "requested",
        state_version: 0,
        proposal_version: 0,
        opportunity_control_version: 4,
        slot_id: null,
        actor_type: "operator",
        actor_agent_id: null,
        actor_admin_id: ADMIN_ID,
        assigned_agent_id: AGENT_ID,
        assigned_operator_id: ADMIN_ID,
        conversation_id: null,
        routing_agent_id: null,
        automation_agent_id: null,
        conversation_control_version: null,
        conversation_automation_version: null,
        source_channel: null,
        evidence_type: null,
        evidence_recorded: false,
        safe_code: null,
        created_at: "2026-09-06T10:00:00Z",
      },
      {
        id: "50000000-0000-0000-0000-000000000002",
        event_type: "scheduled_manual",
        from_status: "slot_selected",
        to_status: state.status,
        state_version: state.stateVersion,
        proposal_version: state.proposalVersion,
        opportunity_control_version: 4,
        slot_id: state.selectedSlotId,
        actor_type: "operator",
        actor_agent_id: null,
        actor_admin_id: ADMIN_ID,
        assigned_agent_id: AGENT_ID,
        assigned_operator_id: ADMIN_ID,
        conversation_id: null,
        routing_agent_id: null,
        automation_agent_id: null,
        conversation_control_version: null,
        conversation_automation_version: null,
        source_channel: null,
        evidence_type: state.status === "scheduled" ? "operator_confirmation" : null,
        evidence_recorded: state.status === "scheduled",
        safe_code: null,
        created_at: "2026-09-06T10:05:00Z",
      },
    ],
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

async function registerMocks(
  page: Page,
  state: MeetingState,
  commands: RecordedCommand[],
  activeAdmin = admin,
) {
  await page.route("**/api/admin/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, activeAdmin);
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith("/meetings/") && request.method() === "GET") {
      return json(route, { items: [summary(state)], total: 1, limit: 100, offset: 0 });
    }
    if (path.endsWith(`/meetings/${MEETING_ID}`) && request.method() === "GET") {
      return json(route, detail(state));
    }
    if (path.endsWith("/meetings/") && request.method() === "POST") {
      record(request, path, commands);
      return json(route, mutation(state, true), 201);
    }
    if (path.includes(`/meetings/${MEETING_ID}/`) && request.method() === "POST") {
      record(request, path, commands);
      if (state.conflictNext) {
        state.conflictNext = false;
        state.stateVersion += 1;
        return json(route, { detail: "meeting state version changed" }, 409);
      }
      if (path.endsWith("/slot-proposals")) {
        state.status = "slots_proposed";
        state.proposalVersion += 1;
      } else if (path.endsWith("/awaiting-response")) {
        state.status = "awaiting_response";
      } else if (path.endsWith("/slot-selections")) {
        state.status = "slot_selected";
        state.selectedSlotId = SLOT_ID;
      } else if (path.endsWith("/manual-schedules")) {
        state.status = "scheduled";
        state.selectedSlotId = SLOT_ID;
      } else if (path.endsWith("/reschedule-requests")) {
        state.status = "reschedule_requested";
      } else if (path.endsWith("/reviews")) {
        state.status = "review_required";
      } else if (path.endsWith("/cancellations")) {
        state.status = "cancelled";
      }
      state.stateVersion += 1;
      return json(route, mutation(state));
    }
    return json(route, { detail: `Mock missing: ${request.method()} ${path}` }, 500);
  });
}

function record(request: ReturnType<Route["request"]>, path: string, commands: RecordedCommand[]) {
  commands.push({
    path,
    body: request.postDataJSON(),
    idempotencyKey: request.headers()["idempotency-key"],
    correlationId: request.headers()["x-correlation-id"],
  });
}

function mutation(state: MeetingState, created = false) {
  return {
    id: MEETING_ID,
    opportunity_id: OPPORTUNITY_ID,
    status: state.status,
    state_version: state.stateVersion,
    proposal_version: state.proposalVersion,
    selected_slot_id: state.selectedSlotId,
    opportunity_stage: state.status === "scheduled" ? "meeting_scheduled" : "qualified",
    opportunity_control_version: 4,
    created,
  };
}

test("operator coordinates a meeting with versioned and idempotent commands", async ({ page }) => {
  await prepare(page);
  const state: MeetingState = {
    status: "slots_proposed",
    stateVersion: 1,
    proposalVersion: 1,
    selectedSlotId: null,
    conflictNext: false,
  };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands);

  await page.goto(`/agents/${AGENT_ID}/meetings`);
  await expect(page.getByRole("heading", { name: "Reuniones de Agente comercial" })).toBeVisible();
  await expect(page.getByText("Calendario externo no configurado", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /Reunión 30000000/ }).click();
  await expect(page.getByRole("button", { name: "Guardar propuesta" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Requerir revisión" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar reunión" })).toBeVisible();
  await expect(page.getByRole("option", { name: "Estado no operable" })).toHaveCount(0);

  await page.getByRole("button", { name: "Marcar esperando respuesta" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].body).toMatchObject({ expected_version: 1 });
  expect(commands[0].idempotencyKey).toMatch(/^meeting-awaiting-/);
  expect(commands[0].correlationId).toBe(`panel-${commands[0].idempotencyKey}`);

  await page.getByRole("radio").check();
  await page.getByRole("button", { name: "Seleccionar horario" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].body).toMatchObject({ expected_version: 2, slot_id: SLOT_ID });

  await expect(
    page.getByRole("region", { name: "Detalle de reunión" }).getByText("Horario elegido", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("radio").check();
  await page.getByLabel("Referencia de evidencia").fill("internal-audit-record-42");
  await page.getByRole("button", { name: "Confirmar reunión" }).click();
  await expect.poll(() => commands.length).toBe(3);
  expect(commands[2].body).toMatchObject({
    expected_version: 3,
    expected_opportunity_version: 4,
    slot_id: SLOT_ID,
    evidence_type: "operator_confirmation",
    evidence_reference: "internal-audit-record-42",
  });
  await expect(
    page.getByRole("region", { name: "Detalle de reunión" }).getByText("Confirmada", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("internal-audit-record-42")).toHaveCount(0);
  await expect(page.getByText("Evidencia registrada", { exact: false })).toBeVisible();

  await page.getByLabel("Motivo obligatorio").first().fill("El contacto pidió otro horario");
  await page.getByRole("button", { name: "Solicitar reprogramación" }).click();
  await expect.poll(() => commands.length).toBe(4);
  expect(commands[3].body).toMatchObject({ expected_version: 4 });
});

test("a stale command reloads the meeting and explains the conflict", async ({ page }) => {
  await prepare(page);
  const state: MeetingState = {
    status: "slots_proposed",
    stateVersion: 1,
    proposalVersion: 1,
    selectedSlotId: null,
    conflictNext: true,
  };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands);

  await page.goto(`/agents/${AGENT_ID}/meetings`);
  await page.getByRole("button", { name: /Reunión 30000000/ }).click();
  await page.getByRole("button", { name: "Marcar esperando respuesta" }).click();

  await expect(page.getByRole("alert")).toContainText("La reunión cambió");
  await expect(
    page.getByRole("region", { name: "Detalle de reunión" }).getByText("v2", { exact: true }),
  ).toBeVisible();
  expect(commands[0].body).toMatchObject({ expected_version: 1 });
});

test("mobile meeting workspace has no horizontal overflow and creates from opportunity", async ({
  page,
}) => {
  await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const state: MeetingState = {
    status: "slots_proposed",
    stateVersion: 1,
    proposalVersion: 1,
    selectedSlotId: null,
    conflictNext: false,
  };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands);

  await page.goto(`/agents/${AGENT_ID}/meetings?opportunity_id=${OPPORTUNITY_ID}`);
  await expect(page.getByLabel("ID de oportunidad").last()).toHaveValue(OPPORTUNITY_ID);
  await page.getByRole("button", { name: "Crear reunión" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].body).toEqual({ opportunity_id: OPPORTUNITY_ID });
  expect(commands[0].idempotencyKey).toMatch(/^meeting-create-/);

  await expect(page.getByRole("button", { name: "Volver a reuniones" })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth);
});

test("meeting read permission does not expose mutation controls", async ({ page }) => {
  await prepare(page);
  const state: MeetingState = {
    status: "slots_proposed",
    stateVersion: 1,
    proposalVersion: 1,
    selectedSlotId: null,
    conflictNext: false,
  };
  const commands: RecordedCommand[] = [];
  await registerMocks(page, state, commands, {
    ...admin,
    permissions: ["profiles.read", "meetings.read"],
  });

  await page.goto(`/agents/${AGENT_ID}/meetings`);
  await page.getByRole("button", { name: /Reunión 30000000/ }).click();
  await expect(page.getByText("Tu rol permite revisar las reuniones", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Guardar propuesta" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Confirmar reunión" })).toHaveCount(0);
  expect(commands).toHaveLength(0);
});
