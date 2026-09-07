import { type Page } from "@playwright/test";

export const AGENT = "00000000-0000-0000-0000-0000000000a1";
export const CHAT = "20000000-0000-0000-0000-000000000002";
export const ADMIN = "10000000-0000-0000-0000-000000000001";
const permissions = ["conversations.read", "conversations.manage"];
export const user = {
  id: ADMIN,
  name: "Operador de prueba",
  email: "operator@example.test",
  permissions,
  is_active: true,
  role: "operator",
};
export const initialSnapshot = {
  revision: "initial",
  unread_conversations: 1,
  active_conversations: 1,
  historical_conversations: 2,
};
export function message(index: number, role = "user", origin: string | null = null) {
  return {
    id: `30000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
    role,
    content: `Mensaje de prueba ${index}`,
    status: "completed",
    origin,
    author_type: role === "user" ? "visitor" : origin === "operator" ? "operator" : "agent",
    actor_admin_id: origin === "operator" ? ADMIN : null,
    tool_names: [],
    created_at: new Date(1_783_000_000_000 + index * 1_000).toISOString(),
  };
}
export function conversation() {
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
    last_message_at: "2026-09-07T10:00:00Z",
    last_message_preview: "Quiero conocer sus servicios",
    last_message_author_type: "visitor",
    owner_agent_id: AGENT,
    owner_agent_name: "Comercial",
    capabilities: permissions,
    unread_count: 1,
    latest_inbound_message_id: message(1).id,
    agent_activity: null as null | { status: string; agent_id: string; name: string },
  };
}
export async function fixture(page: Page, count = 1, rejectInitialToken = false) {
  const state = {
    row: conversation(),
    messages: Array.from({ length: count }, (_, index) => message(index + 1)),
    reads: [] as string[][],
    lifecycle: [] as string[],
    listRequests: 0,
    listUrls: [] as URL[],
    total: 1,
    filterRead: false,
    empty: false,
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
      state.listUrls.push(url);
      state.lifecycle.push(url.searchParams.get("lifecycle") || "");
      const items =
        state.empty ||
        (state.filterRead &&
          url.searchParams.get("unread_only") === "true" &&
          !state.row.unread_count)
          ? []
          : [state.row];
      return reply({
        items,
        total: items.length ? state.total : 0,
        limit: 50,
        offset: Number(url.searchParams.get("offset") || 0),
      });
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
export async function push(page: Page, revision: string, unread = 1) {
  await page.evaluate(
    (snapshot) =>
      (window as unknown as { __inboxPush: (snapshot: unknown) => void }).__inboxPush(snapshot),
    { ...initialSnapshot, revision, unread_conversations: unread },
  );
}
