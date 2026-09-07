import { expect, test, type Page } from "@playwright/test";
import { fixture, push } from "./fixtures/inbox";

async function paginatedFixture(page: Page, count: number) {
  const state = await fixture(page);
  const rows = Array.from({ length: 121 }, (_, index) => ({
    ...state.row,
    id: index === 0 ? state.row.id : `20000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
    display_name: index === 0 ? state.row.display_name : `Conversación ${index + 1}`,
  }));
  const collection = { total: count, urls: [] as URL[] };
  await page.route("**/api/admin/crm/inbox?*", async (route) => {
    const url = new URL(route.request().url());
    collection.urls.push(url);
    const offset = Number(url.searchParams.get("offset"));
    const filtered = url.searchParams.get("search") ? rows.slice(0, 1) : rows.slice(0, collection.total);
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({
      items: filtered.slice(offset, offset + 50), total: filtered.length, limit: 50, offset,
    }) });
  });
  return collection;
}

test("one-page Inbox explains its conversation count and only offers navigation when needed", async ({ page }) => {
  const collection = await paginatedFixture(page, 30);
  await page.goto("/inbox");
  const pagination = page.getByRole("navigation", { name: "Paginación de resultados" });
  await expect(pagination).toContainText("30 conversaciones");
  await expect(pagination).toContainText("Todas en esta página");
  await expect(pagination.getByRole("button")).toHaveCount(0);
  collection.total = 51;
  await push(page, "new-page");
  await expect(pagination).toContainText("1–50 de 51");
  await pagination.getByRole("button", { name: "Siguiente" }).click();
  await expect(pagination).toContainText("51–51 de 51");
  await expect(page.getByRole("button", { name: /Conversación 51 / })).toBeVisible();
  await expect(page.getByRole("button", { name: /Consulta en vivo/ })).toHaveCount(0);
  await expect(pagination.getByRole("button", { name: "Siguiente" })).toBeDisabled();
  await pagination.getByRole("button", { name: "Anterior" }).click();
  await expect(page.getByRole("button", { name: /Consulta en vivo/ })).toBeVisible();
});

test("real pages of 50 navigate, filter from page three and retain the current thread draft", async ({ page }) => {
  const collection = await paginatedFixture(page, 121);
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const draft = page.getByLabel("Respuesta del operador");
  await draft.fill("Borrador pendiente en otra página");
  await page.getByRole("button", { name: "Siguiente", exact: true }).click();
  await expect(page.getByText("51–100 de 121")).toBeVisible();
  await expect(page.getByRole("region", { name: "Conversaciones", exact: true }).getByRole("button")).toHaveCount(50);
  await page.getByRole("button", { name: "Siguiente", exact: true }).click();
  await expect(page.getByText("101–121 de 121")).toBeVisible();
  await expect(page.getByRole("region", { name: "Conversaciones", exact: true }).getByRole("button")).toHaveCount(21);
  await page.getByLabel("Buscar por nombre o identificador de visitante").fill("Consulta");
  await expect.poll(() => collection.urls.at(-1)?.searchParams.get("offset")).toBe("0");
  await expect(page.getByRole("button", { name: /Consulta en vivo/ })).toBeVisible();
  await expect(draft).toHaveValue("Borrador pendiente en otra página");
});

test("a live total shrinking beyond the current page recovers the last valid offset without closing the thread", async ({ page }) => {
  const collection = await paginatedFixture(page, 121);
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const draft = page.getByLabel("Respuesta del operador");
  await draft.fill("No perder al cambiar la colección");
  await page.getByRole("button", { name: "Siguiente", exact: true }).click();
  await expect(page.getByText("51–100 de 121")).toBeVisible();
  await page.getByRole("button", { name: "Siguiente", exact: true }).click();
  await expect(page.getByText("101–121 de 121")).toBeVisible();
  collection.total = 75;
  await push(page, "closed-last-page");
  await expect.poll(() => collection.urls.at(-1)?.searchParams.get("offset")).toBe("50");
  await expect(page.getByText("51–75 de 75")).toBeVisible();
  await expect(draft).toHaveValue("No perder al cambiar la colección");
  collection.total = 30;
  await push(page, "one-page-left");
  await expect.poll(() => collection.urls.at(-1)?.searchParams.get("offset")).toBe("0");
  await expect(page.getByRole("navigation", { name: "Paginación de resultados" })).toContainText("30 conversaciones");
  collection.total = 0;
  await push(page, "empty-collection");
  await expect(page.getByText("Sin resultados", { exact: true })).toBeVisible();
  await expect(draft).toHaveValue("No perder al cambiar la colección");
});
