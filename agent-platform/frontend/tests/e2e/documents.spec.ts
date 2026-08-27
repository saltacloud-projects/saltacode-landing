import { expect, test, type Page, type Route } from "@playwright/test";

const AREA_ID = "00000000-0000-0000-0000-000000000001";
const FOLDER_ID = "10000000-0000-0000-0000-000000000001";
const DOCUMENT_ID = "20000000-0000-0000-0000-000000000001";

const user = {
  id: "30000000-0000-0000-0000-000000000001",
  email: "documents@example.test",
  name: "Gestión documental",
  role: "document_manager",
  is_active: true,
  must_change_password: false,
  permissions: ["documents.read", "documents.manage"],
};

const settings = {
  enabled: true,
  embedding_model: "text-embedding-3-small",
  embedding_dimensions: 1536,
  vision_model: "gpt-4.1-mini",
  max_file_bytes: 104857600,
  max_batch_bytes: 2147483648,
  retention_days: 30,
  chunk_tokens: 800,
  chunk_overlap_tokens: 120,
  retrieval_top_k: 8,
  min_relevance_score: 0.35,
  vector_weight: 0.7,
  lexical_weight: 0.3,
  ocr_enabled: true,
};

const documentRow = {
  id: DOCUMENT_ID,
  reference_code: "DOC-AABBCCDD",
  folder_id: FOLDER_ID,
  folder_name: "General",
  area_id: AREA_ID,
  area_name: "General",
  title: "Manual de prueba",
  description: null,
  internal_code: null,
  responsible: null,
  effective_from: null,
  effective_to: null,
  status: "published",
  deleted_at: null,
  purge_after: null,
  current_version: {
    id: "40000000-0000-0000-0000-000000000001",
    version_number: 1,
    status: "ready",
    original_filename: "manual.txt",
    size_bytes: 120,
    page_count: 0,
    chunk_count: 1,
    extraction_method: "native",
    error_message: null,
  },
  current_job: null,
  updated_at: "2026-06-30T12:00:00Z",
};

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
}

async function mockPanel(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("tokens", JSON.stringify({ access_token: "test", refresh_token: "test" }));
  });
  await page.route("**/api/admin/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/auth/me")) return json(route, user);
    if (path.endsWith("/documents/areas")) return json(route, [{ id: AREA_ID, name: "General", slug: "general", description: null, is_general: true, is_active: true, folder_count: 1, document_count: 1 }]);
    if (path.endsWith("/documents/folders")) return json(route, [{ id: FOLDER_ID, area_id: AREA_ID, parent_id: null, name: "General", document_count: 1 }]);
    if (path.endsWith("/documents/settings")) return json(route, settings);
    if (path.endsWith("/documents/stats")) return json(route, { documents_total: 1, published: 1, processing: 0, failed: 0, deleted: 0, chunks: 1, storage_bytes: 120, queue_depth: 0, worker_last_activity: new Date().toISOString() });
    if (path.endsWith("/documents/upload") && route.request().method() === "POST") return json(route, { accepted: [{ document_id: DOCUMENT_ID, reference_code: "DOC-NEW00001", version_id: "v", job_id: "j", filename: "nuevo.txt", duplicate_hash: false }], rejected: [] }, 202);
    if (path.endsWith(`/documents/${DOCUMENT_ID}/replace`) && route.request().method() === "POST") return json(route, { accepted: [{ document_id: DOCUMENT_ID, reference_code: "DOC-AABBCCDD", version_id: "v2", job_id: "j2", filename: "reemplazo.txt", duplicate_hash: true }], rejected: [] }, 202);
    if (path.endsWith("/documents/") && route.request().method() === "GET") return json(route, { items: [documentRow], total: 1, limit: 50, offset: 0 });
    return json(route, { detail: `Mock faltante: ${route.request().method()} ${path}` }, 500);
  });
}

test("el gestor documental sólo ve Documentos y no puede navegar a otros módulos", async ({ page }) => {
  await mockPanel(page);
  await page.goto("/documents");
  await expect(page.getByRole("link", { name: "Documentos" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Herramientas" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Usuarios" })).toHaveCount(0);
  await expect(page.getByText("Accesos del panel")).toHaveCount(0);
  await page.goto("/tools");
  await expect(page).toHaveURL(/\/documents$/);
});

test("seleccionar un archivo habilita un flujo visible y lo envía", async ({ page }) => {
  await mockPanel(page);
  await page.goto("/documents");
  const submit = page.getByTestId("upload-submit");
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByText("Elegí al menos un archivo o una carpeta antes de subir.")).toBeVisible();

  await page.getByTestId("upload-file-input").setInputFiles({
    name: "nuevo.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("contenido documental de prueba"),
  });
  await expect(page.getByText(/1 archivo\(s\) seleccionado\(s\)/)).toBeVisible();
  await expect(submit).toContainText("Subir 1");
  await submit.click();
  await expect(page.getByText("1 archivo(s) encolado(s).")).toBeVisible();
});

test("reemplazar informa el versionado y los duplicados", async ({ page }) => {
  await mockPanel(page);
  await page.goto("/documents");
  const chooserPromise = page.waitForEvent("filechooser");
  await page.getByTitle("Reemplazar").click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: "reemplazo.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("contenido documental de reemplazo"),
  });
  await expect(page.getByText(/Reemplazo encolado como nueva versión/)).toBeVisible();
});
