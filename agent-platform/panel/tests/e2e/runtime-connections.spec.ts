import { expect, test, type Page, type Route } from "@playwright/test";

const AGENT_ID = "00000000-0000-0000-0000-0000000000a1";
const PROVIDER_ID = "10000000-0000-0000-0000-0000000000a1";
const CHANNEL_ID = "20000000-0000-0000-0000-0000000000a1";
const WHATSAPP_CHANNEL_ID = "20000000-0000-0000-0000-0000000000b2";

const admin = {
  id: "30000000-0000-0000-0000-000000000001",
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
  description: "Agent description",
  prompt_identity: "Identity",
  prompt_domain: "Domain",
  prompt_guardrails: "Guardrails",
  unauthorized_message: "Unauthorized",
  error_message: "Error",
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

const provider = {
  id: PROVIDER_ID,
  name: "OpenAI principal",
  slug: "openai-principal",
  provider_type: "openai",
  base_url: null,
  settings: {},
  has_credentials: true,
  is_active: true,
  created_by: "admin@example.test",
  updated_by: "admin@example.test",
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

const channelConnection = {
  id: CHANNEL_ID,
  name: "Web pública",
  slug: "web-publica",
  channel: "web",
  adapter_key: "web_builtin",
  version: 2,
  external_account_id: "landing",
  settings: {},
  has_credentials: false,
  is_active: true,
  created_by: "admin@example.test",
  updated_by: "admin@example.test",
  created_at: "2026-08-27T10:00:00Z",
  updated_at: "2026-08-27T10:00:00Z",
};

const whatsappConnection = {
  ...channelConnection,
  id: WHATSAPP_CHANNEL_ID,
  name: "WhatsApp comercial",
  slug: "whatsapp-comercial",
  channel: "whatsapp",
  adapter_key: "meta_whatsapp_cloud",
  version: 4,
  external_account_id: "waba-123",
  has_credentials: true,
};

const channelAdapters = [
  {
    adapter_key: "web_builtin",
    channel: "web",
    implementation_status: "implemented",
    adapter_implemented: true,
    capabilities: ["inbound_text", "outbound_text", "resumable_stream"],
    credentials_required: false,
    blocking_codes: [],
  },
  {
    adapter_key: "meta_whatsapp_cloud",
    channel: "whatsapp",
    implementation_status: "implemented",
    adapter_implemented: true,
    capabilities: ["inbound_text", "outbound_text"],
    credentials_required: true,
    blocking_codes: [],
  },
  {
    adapter_key: "email",
    channel: "email",
    implementation_status: "planned",
    adapter_implemented: false,
    capabilities: ["inbound_text", "outbound_text"],
    credentials_required: true,
    blocking_codes: ["provider_required"],
  },
  {
    adapter_key: "meta_instagram_graph",
    channel: "instagram_dm",
    implementation_status: "planned",
    adapter_implemented: false,
    capabilities: ["inbound_text", "outbound_text"],
    credentials_required: true,
    blocking_codes: ["blocked_external"],
  },
  {
    adapter_key: "meta_messenger_graph",
    channel: "facebook_messenger",
    implementation_status: "planned",
    adapter_implemented: false,
    capabilities: ["inbound_text", "outbound_text"],
    credentials_required: true,
    blocking_codes: ["blocked_external"],
  },
] as const;

function readiness(connection: typeof channelConnection | typeof whatsappConnection) {
  return {
    connection_id: connection.id,
    name: connection.name,
    slug: connection.slug,
    channel: connection.channel,
    adapter_key: connection.adapter_key,
    version: connection.version,
    is_active: connection.is_active,
    readiness: connection.channel === "web" ? "traffic_observed" : "configured_unverified",
    adapter_implemented: true,
    settings_valid: true,
    credentials_state: connection.channel === "web" ? "not_required" : "stored_unverified",
    routing_state: "active",
    active_route_count: 1,
    last_inbound_at: connection.channel === "web" ? "2026-08-27T10:00:00Z" : null,
    last_outbound_at: null,
    blocking_codes: connection.channel === "web" ? [] : ["traffic_not_observed"],
  };
}

const channelCatalog = {
  adapters: channelAdapters,
  connections: [readiness(channelConnection), readiness(whatsappConnection)],
};

const runtime = {
  id: "40000000-0000-0000-0000-000000000001",
  agent_id: AGENT_ID,
  provider_connection_id: PROVIDER_ID,
  chat_model: "gpt-4.1-mini",
  transcription_model: "gpt-4o-mini-transcribe",
  temperature: 0.5,
  max_output_tokens: 2000,
  max_iterations: 12,
  max_tool_calls: 25,
  loop_timeout_seconds: 150,
  tool_timeout_seconds: 60,
  tool_result_max_chars: 16000,
  history_message_limit: 20,
  history_cache_ttl_seconds: 300,
  summary_enabled: true,
  summary_trigger_messages: 10,
  summary_max_chars: 60000,
  rag_enabled: false,
  rag_retrieval_top_k: 8,
  rag_min_relevance_score: 0.35,
  rag_vector_weight: 0.7,
  rag_lexical_weight: 0.3,
  provider_ready: true,
};

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function mockAdmin(page: Page, handle: (route: Route, path: string) => Promise<boolean>) {
  await page.addInitScript(() => {
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" }));
  });
  await page.route("**/api/admin/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) return json(route, admin);
    if (path.endsWith("/profiles/")) return json(route, [profile]);
    if (path.endsWith("/channel-catalog")) return json(route, channelCatalog);
    if (await handle(route, path)) return;
    return json(route, { detail: `Mock missing: ${route.request().method()} ${path}` }, 500);
  });
}

test("provider secret remains write-only and rotation sends only the new value", async ({ page }) => {
  let patchBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/provider-connections") && route.request().method() === "GET") {
      await json(route, [provider]); return true;
    }
    if (path.endsWith(`/provider-connections/${PROVIDER_ID}`) && route.request().method() === "PATCH") {
      patchBody = route.request().postDataJSON();
      await json(route, provider); return true;
    }
    return false;
  });

  await page.goto("/shared/provider-connections");
  await expect(page.getByText("Configurada (write-only)")).toBeVisible();
  await page.getByRole("button", { name: "Editar o rotar" }).click();
  const secretInput = page.getByLabel("Nueva API key (vacío conserva el secreto actual)");
  await expect(secretInput).toHaveValue("");
  await secretInput.fill("rotated-secret");
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect.poll(() => patchBody).not.toBeNull();
  expect(patchBody).toMatchObject({ credentials: { api_key: "rotated-secret" } });
  expect(JSON.stringify(patchBody)).not.toContain("stored-secret");
});

test("provider connectivity test uses the server endpoint without requesting a secret", async ({ page }) => {
  let testCalled = false;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/provider-connections") && route.request().method() === "GET") {
      await json(route, [provider]); return true;
    }
    if (path.endsWith(`/provider-connections/${PROVIDER_ID}/test`) && route.request().method() === "POST") {
      testCalled = true;
      await json(route, { ok: true, duration_ms: 42, error_code: null }); return true;
    }
    return false;
  });

  await page.goto("/shared/provider-connections");
  await page.getByRole("button", { name: "Probar conexión" }).click();
  await expect(page.getByText("Proveedor disponible · 42 ms.")).toBeVisible();
  expect(testCalled).toBe(true);
});

test("WhatsApp rotation sends exactly its three write-only credentials", async ({ page }) => {
  let patchBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections") && route.request().method() === "GET") {
      await json(route, [channelConnection, whatsappConnection]); return true;
    }
    if (path.endsWith(`/channel-connections/${WHATSAPP_CHANNEL_ID}`) && route.request().method() === "PATCH") {
      patchBody = route.request().postDataJSON();
      await json(route, whatsappConnection); return true;
    }
    return false;
  });

  await page.goto("/shared/channel-connections");
  await page.getByRole("article").filter({ hasText: "WhatsApp comercial" }).getByRole("button", { name: "Editar o rotar" }).click();
  await page.getByLabel("Access token").fill("access-new");
  await page.getByLabel("Verify token").fill("verify-new");
  await page.getByLabel("App secret").fill("secret-new");
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect.poll(() => patchBody).not.toBeNull();
  expect(patchBody).toMatchObject({
    expected_version: 4,
    credentials: {
      access_token: "access-new",
      verify_token: "verify-new",
      app_secret: "secret-new",
    },
  });
  expect((patchBody as { credentials: Record<string, string> }).credentials).not.toHaveProperty("api_key");
});

test("web channel creation never exposes or sends credential fields", async ({ page }) => {
  let createBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections") && route.request().method() === "GET") {
      await json(route, []); return true;
    }
    if (path.endsWith("/channel-connections") && route.request().method() === "POST") {
      createBody = route.request().postDataJSON();
      await json(route, channelConnection, 201); return true;
    }
    return false;
  });

  await page.goto("/shared/channel-connections");
  await page.getByRole("button", { name: "Nueva conexión" }).click();
  await expect(page.getByText("El canal web no admite ni necesita credenciales.")).toBeVisible();
  await expect(page.getByLabel("Access token")).toHaveCount(0);
  await page.getByLabel("Nombre").fill("Web pública");
  await page.getByLabel("Slug").fill("web-publica");
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect.poll(() => createBody).not.toBeNull();
  expect(createBody).not.toHaveProperty("credentials");
  expect(createBody).toMatchObject({ channel: "web", adapter_key: "web_builtin" });
});

test("channel catalog shows planned integrations without offering activation", async ({ page }) => {
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections") && route.request().method() === "GET") {
      await json(route, [channelConnection, whatsappConnection]);
      return true;
    }
    return false;
  });

  await page.goto("/shared/channel-connections");
  await expect(page.getByRole("heading", { name: "Email" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Instagram DM" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Facebook Messenger" })).toBeVisible();
  await expect(page.getByText("Integración pendiente")).toHaveCount(3);

  await page.getByRole("button", { name: "Nueva conexión" }).click();
  const channelOptions = page.getByLabel("Canal").locator("option");
  await expect(channelOptions).toHaveCount(2);
  await expect(channelOptions.filter({ hasText: "Email" })).toHaveCount(0);
});

test("channel catalog and connection form avoid horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections") && route.request().method() === "GET") {
      await json(route, [channelConnection, whatsappConnection]);
      return true;
    }
    return false;
  });

  await page.goto("/shared/channel-connections");
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await page.getByRole("button", { name: "Nueva conexión" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("stale channel connection edit reloads current state before another attempt", async ({
  page,
}) => {
  let getCount = 0;
  let patchBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections") && route.request().method() === "GET") {
      getCount += 1;
      await json(route, [whatsappConnection]);
      return true;
    }
    if (
      path.endsWith(`/channel-connections/${WHATSAPP_CHANNEL_ID}`) &&
      route.request().method() === "PATCH"
    ) {
      patchBody = route.request().postDataJSON();
      await json(route, { detail: "channel_connection_version_conflict" }, 409);
      return true;
    }
    return false;
  });

  await page.goto("/shared/channel-connections");
  await page.getByRole("button", { name: "Editar o rotar" }).click();
  await page.getByLabel("Nombre").fill("WhatsApp actualizado");
  await page.getByRole("button", { name: "Guardar" }).click();

  await expect.poll(() => patchBody).not.toBeNull();
  expect(patchBody).toMatchObject({ expected_version: 4 });
  await expect.poll(() => getCount).toBeGreaterThanOrEqual(2);
  await expect(page.getByText(/La conexión cambió en otra sesión/)).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("channel connection deactivation sends the version read by the operator", async ({ page }) => {
  let deactivateBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections") && route.request().method() === "GET") {
      await json(route, [channelConnection]);
      return true;
    }
    if (
      path.endsWith(`/channel-connections/${CHANNEL_ID}/deactivate`) &&
      route.request().method() === "POST"
    ) {
      deactivateBody = route.request().postDataJSON();
      await json(route, { ...channelConnection, version: 3, is_active: false });
      return true;
    }
    return false;
  });

  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/shared/channel-connections");
  await page.getByRole("button", { name: "Desactivar" }).click();

  await expect.poll(() => deactivateBody).not.toBeNull();
  expect(deactivateBody).toEqual({ expected_version: 2 });
});

test("runtime save can disconnect its provider without response-only fields", async ({ page }) => {
  let runtimePatch: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/provider-connections")) { await json(route, [provider]); return true; }
    if (path.endsWith(`/profiles/${AGENT_ID}/runtime`)) {
      if (route.request().method() === "GET") { await json(route, runtime); return true; }
      runtimePatch = route.request().postDataJSON();
      await json(route, { ...runtime, ...runtimePatch }); return true;
    }
    return false;
  });

  await page.goto(`/agents/${AGENT_ID}/runtime`);
  await page.getByLabel("Conexión de IA").selectOption("");
  await page.getByLabel("Modelo de chat").fill("gpt-5-mini");
  await page.getByLabel("Iteraciones máximas").fill("9");
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect.poll(() => runtimePatch).not.toBeNull();
  expect(runtimePatch).toMatchObject({ chat_model: "gpt-5-mini", max_iterations: 9, provider_connection_id: null });
  expect(runtimePatch).not.toHaveProperty("agent_id");
  expect(runtimePatch).not.toHaveProperty("provider_ready");
});

test("channel route creation binds the selected agent server-side", async ({ page }) => {
  let createBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections")) { await json(route, [channelConnection]); return true; }
    if (path.endsWith(`/profiles/${AGENT_ID}/routes`)) {
      if (route.request().method() === "GET") { await json(route, []); return true; }
      createBody = route.request().postDataJSON();
      await json(route, { id: "route-id", agent_id: AGENT_ID, ...createBody, created_at: "2026-08-27T10:00:00Z", updated_at: "2026-08-27T10:00:00Z" }, 201);
      return true;
    }
    return false;
  });

  await page.goto(`/agents/${AGENT_ID}/channels`);
  await page.getByRole("button", { name: "Nueva ruta" }).click();
  await page.getByLabel("Route key").fill("landing:principal");
  await page.getByRole("button", { name: "Crear ruta" }).click();
  await expect.poll(() => createBody).not.toBeNull();
  expect(createBody).toEqual({ channel: "web", route_key: "landing:principal", channel_connection_id: CHANNEL_ID, is_active: true });
});

test("agent channel routes remain usable without horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections")) {
      await json(route, [channelConnection]);
      return true;
    }
    if (path.endsWith(`/profiles/${AGENT_ID}/routes`)) {
      await json(route, []);
      return true;
    }
    return false;
  });

  await page.goto(`/agents/${AGENT_ID}/channels`);
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
  await page.getByRole("button", { name: "Nueva ruta" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true);
});

test("route deactivation uses CAS and reloads after a stale version", async ({ page }) => {
  const routeRow = {
    id: "50000000-0000-0000-0000-000000000001",
    agent_id: AGENT_ID,
    channel: "web",
    version: 7,
    route_key: "landing:principal",
    channel_connection_id: CHANNEL_ID,
    is_active: true,
    created_at: "2026-08-27T10:00:00Z",
    updated_at: "2026-08-27T10:00:00Z",
  };
  let getCount = 0;
  let deactivateBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections")) {
      await json(route, [channelConnection]);
      return true;
    }
    if (
      path.endsWith(`/profiles/${AGENT_ID}/routes`) &&
      route.request().method() === "GET"
    ) {
      getCount += 1;
      await json(route, [routeRow]);
      return true;
    }
    if (
      path.endsWith(`/profiles/${AGENT_ID}/routes/${routeRow.id}/deactivate`) &&
      route.request().method() === "POST"
    ) {
      deactivateBody = route.request().postDataJSON();
      await json(route, { detail: "channel_route_version_conflict" }, 409);
      return true;
    }
    return false;
  });

  page.on("dialog", (dialog) => dialog.accept());
  await page.goto(`/agents/${AGENT_ID}/channels`);
  await page.getByRole("button", { name: "Desactivar" }).click();

  await expect.poll(() => deactivateBody).not.toBeNull();
  expect(deactivateBody).toEqual({ expected_version: 7 });
  await expect.poll(() => getCount).toBeGreaterThanOrEqual(2);
  await expect(page.getByText(/La ruta cambió en otra sesión/)).toBeVisible();
});

test("route reactivation sends the version read by the operator", async ({ page }) => {
  const routeRow = {
    id: "50000000-0000-0000-0000-000000000002",
    agent_id: AGENT_ID,
    channel: "web",
    version: 3,
    route_key: "landing:secondary",
    channel_connection_id: CHANNEL_ID,
    is_active: false,
    created_at: "2026-08-27T10:00:00Z",
    updated_at: "2026-08-27T10:00:00Z",
  };
  let patchBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/channel-connections")) {
      await json(route, [channelConnection]);
      return true;
    }
    if (
      path.endsWith(`/profiles/${AGENT_ID}/routes`) &&
      route.request().method() === "GET"
    ) {
      await json(route, [routeRow]);
      return true;
    }
    if (
      path.endsWith(`/profiles/${AGENT_ID}/routes/${routeRow.id}`) &&
      route.request().method() === "PATCH"
    ) {
      patchBody = route.request().postDataJSON();
      await json(route, { ...routeRow, version: 4, is_active: true });
      return true;
    }
    return false;
  });

  await page.goto(`/agents/${AGENT_ID}/channels`);
  await page.getByRole("button", { name: "Reactivar" }).click();

  await expect.poll(() => patchBody).not.toBeNull();
  expect(patchBody).toEqual({ is_active: true, expected_version: 3 });
});

test("PromptLab preview and execution send the selected agent explicitly", async ({ page }) => {
  let previewBody: Record<string, unknown> | null = null;
  let testBody: Record<string, unknown> | null = null;
  let searchAgentId: string | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith(`/agents/${AGENT_ID}/authorized-users`)) {
      await json(route, [{ id: "user-1", agent_id: AGENT_ID, phone_number: "5493870000000", name: "Contacto", notes: null, is_active: true, has_all_area_access: false, area_ids: [], created_at: "2026-08-27T10:00:00Z", updated_at: "2026-08-27T10:00:00Z" }]);
      return true;
    }
    if (path.endsWith("/promptlab/prompt-preview")) {
      previewBody = route.request().postDataJSON();
      await json(route, { system_prompt: "Prompt Alpha", char_count: 12, profile_name: "Agent Alpha", placeholders_resolved: [] });
      return true;
    }
    if (path.endsWith("/promptlab/test-agent")) {
      testBody = route.request().postDataJSON();
      await json(route, { response_text: "OK", tools_used: [], tool_invocations: [], iterations: 1, total_tool_calls: 0, duration_ms: 10, status: "success", rag_hits: [] });
      return true;
    }
    if (path.endsWith("/promptlab/search-conversations")) {
      searchAgentId = new URL(route.request().url()).searchParams.get("agent_id");
      await json(route, [{ id: "message-1", conversation_id: "conversation-1", display_name: "Visitante web", channel: "web", route_key: "landing:principal", external_thread_id: "thread-public", role: "user", content: "Necesito un presupuesto", created_at: "2026-08-27T10:00:00Z" }]);
      return true;
    }
    return false;
  });

  await page.goto(`/agents/${AGENT_ID}/promptlab`);
  await page.getByRole("button", { name: "Cargar prompt actual" }).click();
  await expect.poll(() => previewBody).not.toBeNull();
  expect(previewBody).toEqual({ agent_id: AGENT_ID });
  await page.getByLabel("Mensaje").fill("Hola");
  await page.getByRole("button", { name: "Enviar" }).click();
  await expect.poll(() => testBody).not.toBeNull();
  expect(testBody).toMatchObject({ agent_id: AGENT_ID, message: "Hola" });
  await page.getByLabel("Texto a buscar en conversaciones").fill("presupuesto");
  await page.getByRole("button", { name: "Buscar" }).click();
  await expect.poll(() => searchAgentId).toBe(AGENT_ID);
  await expect(page.getByText("Visitante web")).toBeVisible();
  await expect(page.getByText("landing:principal")).toBeVisible();
});
