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
  external_account_id: "waba-123",
  has_credentials: true,
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
  expect(patchBody).toMatchObject({ credentials: { access_token: "access-new", verify_token: "verify-new", app_secret: "secret-new" } });
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
  expect(createBody).toMatchObject({ channel: "web" });
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

test("PromptLab preview and execution send the selected agent explicitly", async ({ page }) => {
  let previewBody: Record<string, unknown> | null = null;
  let testBody: Record<string, unknown> | null = null;
  await mockAdmin(page, async (route, path) => {
    if (path.endsWith("/users/")) { await json(route, []); return true; }
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
});
