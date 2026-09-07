import { expect, type Page, test } from "@playwright/test";
import { fixture, message, push } from "./fixtures/inbox";

const searchLabel = "Buscar por nombre o identificador de visitante";
async function filters(page: Page) {
  await page.getByText("Filtros y alcance", { exact: true }).click();
}

test("search and quick views reach the server, reset pagination and keep global unread independent", async ({
  page,
}) => {
  const state = await fixture(page);
  state.total = 70;
  await page.goto("/inbox");
  await page.getByRole("button", { name: "Siguiente", exact: true }).click();
  await expect.poll(() => state.listUrls.at(-1)?.searchParams.get("offset")).toBe("50");
  await page.getByLabel(searchLabel).fill("  Consulta %_  ");
  await expect.poll(() => state.listUrls.at(-1)?.searchParams.get("search")).toBe("Consulta %_");
  expect(state.listUrls.at(-1)?.searchParams.get("offset")).toBe("0");
  await expect(page.getByLabel(searchLabel)).toHaveAttribute("maxlength", "120");
  await expect(page.getByLabel(searchLabel)).toBeFocused();
  await page.getByRole("button", { name: "No leídas", exact: true }).click();
  await expect.poll(() => state.listUrls.at(-1)?.searchParams.get("unread_only")).toBe("true");
  expect(state.listUrls.at(-1)?.searchParams.get("lifecycle")).toBe("active");
  await page.getByRole("button", { name: "Historial", exact: true }).click();
  await expect.poll(() => state.listUrls.at(-1)?.searchParams.get("lifecycle")).toBe("history");
  expect(state.listUrls.at(-1)?.searchParams.has("unread_only")).toBe(false);
  await expect(
    page.getByRole("status", { name: "1 conversaciones activas sin leer", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Todas", exact: true }).click();
  await expect.poll(() => state.listUrls.at(-1)?.searchParams.get("lifecycle")).toBe("all");
  await page.getByRole("button", { name: "Limpiar búsqueda" }).click();
  await expect.poll(() => state.listUrls.at(-1)?.searchParams.has("search")).toBe(false);
  state.empty = true;
  await page.getByLabel(searchLabel).fill("Sin coincidencias");
  await expect(page.getByText("No hay conversaciones para estos filtros.")).toBeVisible();
  await expect(page.getByText("Sin resultados", { exact: true })).toBeVisible();
});

test.describe("local calendar last-message filters", () => {
  test.use({ timezoneId: "America/New_York" });

  test("today, 7 and 30 calendar days cross DST with exclusive next-day bounds", async ({
    page,
  }) => {
    await page.clock.install({ time: new Date("2026-03-08T16:00:00Z") });
    const state = await fixture(page);
    await page.goto("/inbox");
    await filters(page);
    await expect(page.getByText(/America\/New_York/)).toBeVisible();
    for (const [period, from] of [
      ["today", "2026-03-08T05:00:00.000Z"],
      ["7d", "2026-03-02T05:00:00.000Z"],
      ["30d", "2026-02-07T05:00:00.000Z"],
    ]) {
      await page.getByLabel("Último mensaje", { exact: true }).selectOption(period);
      await expect
        .poll(() => state.listUrls.at(-1)?.searchParams.get("last_message_from"))
        .toBe(from);
      expect(state.listUrls.at(-1)?.searchParams.get("last_message_before")).toBe(
        "2026-03-09T04:00:00.000Z",
      );
      expect(state.listUrls.at(-1)?.searchParams.has("updated_after")).toBe(false);
    }
    await page.getByLabel("Último mensaje", { exact: true }).selectOption("all");
    await expect
      .poll(() => state.listUrls.at(-1)?.searchParams.has("last_message_from"))
      .toBe(false);
    expect(state.listUrls.at(-1)?.searchParams.has("last_message_before")).toBe(false);
  });

  test("custom inclusive dates reject incomplete and reversed ranges and include 25-hour fall-back day", async ({
    page,
  }) => {
    const state = await fixture(page);
    await page.goto("/inbox");
    await filters(page);
    await page.getByLabel("Último mensaje", { exact: true }).selectOption("custom");
    const apply = page.getByRole("button", { name: "Aplicar fechas" });
    await expect(apply).toBeDisabled();
    await page.getByLabel("Desde", { exact: true }).fill("2026-11-02");
    await expect(apply).toBeDisabled();
    await page.getByLabel("Hasta", { exact: true }).fill("2026-11-01");
    await expect(apply).toBeDisabled();
    await expect(
      page.getByText("La fecha desde no puede ser posterior a la fecha hasta."),
    ).toBeVisible();
    expect(state.listUrls.every((url) => !url.searchParams.has("last_message_from"))).toBe(true);
    await page.getByLabel("Desde", { exact: true }).fill("2026-11-01");
    await apply.click();
    await expect
      .poll(() => state.listUrls.at(-1)?.searchParams.get("last_message_from"))
      .toBe("2026-11-01T04:00:00.000Z");
    expect(state.listUrls.at(-1)?.searchParams.get("last_message_before")).toBe(
      "2026-11-02T05:00:00.000Z",
    );
    await page.getByLabel("Desde", { exact: true }).fill("");
    await expect(apply).toBeDisabled();
    expect(state.listUrls.at(-1)?.searchParams.get("last_message_from")).toBe(
      "2026-11-01T04:00:00.000Z",
    );
  });

  test("an open today view reevaluates at local midnight without another live event", async ({
    page,
  }) => {
    await page.clock.install({ time: new Date("2026-03-09T03:59:30Z") });
    const state = await fixture(page);
    await page.goto("/inbox");
    await filters(page);
    await page.getByLabel("Último mensaje", { exact: true }).selectOption("today");
    await expect
      .poll(() => state.listUrls.at(-1)?.searchParams.get("last_message_from"))
      .toBe("2026-03-08T05:00:00.000Z");
    await page.clock.fastForward(31_000);
    await expect
      .poll(() => state.listUrls.at(-1)?.searchParams.get("last_message_from"))
      .toBe("2026-03-09T04:00:00.000Z");
    expect(state.listUrls.at(-1)?.searchParams.get("last_message_before")).toBe(
      "2026-03-10T04:00:00.000Z",
    );
  });
});

test("acknowledging an unread row can remove it without closing its thread or discarding a draft", async ({
  page,
}) => {
  const state = await fixture(page);
  state.filterRead = true;
  await page.goto("/inbox");
  await page.getByRole("button", { name: "No leídas", exact: true }).click();
  await expect.poll(() => state.listUrls.at(-1)?.searchParams.get("unread_only")).toBe("true");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  const draft = page.getByLabel("Respuesta del operador");
  await draft.fill("La respuesta permanece disponible");
  await expect.poll(() => state.reads.length).toBeGreaterThan(0);
  await push(page, "read-removed", 0);
  await expect(page.getByRole("button", { name: /Consulta en vivo/ })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Consulta en vivo" })).toBeVisible();
  await expect(draft).toHaveValue("La respuesta permanece disponible");
  await expect(draft).toBeFocused();
  await page.getByRole("button", { name: "Activas", exact: true }).click();
  await expect(page.getByRole("button", { name: /Consulta en vivo/ })).toBeVisible();
  await expect(draft).toHaveValue("La respuesta permanece disponible");
});

test("progressive controls do not acknowledge obscured inbound and Escape restores controls focus", async ({
  page,
}) => {
  const state = await fixture(page);
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect.poll(() => state.reads.length).toBe(1);
  const toggle = page.getByRole("button", { name: "Detalles y controles" });
  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  state.messages.push(message(2));
  state.row.unread_count = 1;
  state.row.latest_inbound_message_id = message(2).id;
  await push(page, "covered-message");
  await expect(page.getByText("Mensaje de prueba 2", { exact: true })).toBeHidden();
  expect(state.reads).toHaveLength(1);
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByText("Mensaje de prueba 2", { exact: true })).toBeVisible();
  await expect.poll(() => state.reads.length).toBe(2);
});

for (const width of [320, 390, 1440]) {
  test(`messaging workspace at ${width}px has separate log scrolling, readable authors and reachable controls`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.clock.setFixedTime(new Date("2026-09-07T15:00:00Z"));
    const state = await fixture(page, 36);
    state.messages = state.messages.map((item, index) => ({
      ...item,
      created_at: index < 32 ? "2026-09-06T10:00:00Z" : "2026-09-07T12:00:00Z",
      content:
        index === 33
          ? "Palabra".repeat(150)
          : index === 35
            ? "Perfecto, podemos ayudarte a definir el alcance y preparar la próxima reunión."
            : item.content,
      role: index % 2 ? "assistant" : "user",
      origin: index === 35 ? "operator" : "channel",
      author_type: index === 35 ? "operator" : index % 2 ? "agent" : "visitor",
    }));
    await page.goto("/inbox");
    await expect(page.getByRole("button", { name: "No leídas", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.getByRole("button", { name: /Consulta en vivo/ }).click();
    const log = page.getByRole("log");
    const composer = page.getByLabel("Respuesta del operador");
    await composer.fill("Estamos revisando tu proyecto");
    await expect(log.getByText("Operador", { exact: true })).toBeVisible();
    const before = await composer.boundingBox();
    const header = await page.getByRole("heading", { name: "Consulta en vivo" }).boundingBox();
    const computed = await log.locator("article").evaluateAll((articles) =>
      articles.map((article) => ({
        name: article.getAttribute("aria-label"),
        background: getComputedStyle(article).backgroundColor,
      })),
    );
    expect(computed.find((item) => item.name?.startsWith("Operador"))?.background).not.toBe(
      "rgba(0, 0, 0, 0)",
    );
    expect(computed.find((item) => item.name?.startsWith("Agente"))?.background).not.toBe(
      computed.find((item) => item.name?.startsWith("Visitante"))?.background,
    );
    await log.evaluate((element) => {
      element.scrollTop = 0;
      element.dispatchEvent(new Event("scroll"));
    });
    await expect(log.getByRole("heading", { name: "Ayer", exact: true })).toBeVisible();
    expect(await composer.boundingBox()).toEqual(before);
    expect(await page.getByRole("heading", { name: "Consulta en vivo" }).boundingBox()).toEqual(
      header,
    );
    expect(before!.y + before!.height).toBeLessThanOrEqual(900);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(await log.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    await log.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
      element.dispatchEvent(new Event("scroll"));
    });
    state.messages.at(-3)!.content =
      "Podemos desarrollar una web a medida e integrarla con las herramientas de tu empresa.";
    state.messages.at(-2)!.content =
      "Me interesa. ¿Podemos coordinar una reunión para revisar el proyecto?";
    await push(page, "readable-screenshot");
    await expect(log.getByText(state.messages.at(-3)!.content, { exact: true })).toBeVisible();
    await log.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    await page.screenshot({
      path: testInfo.outputPath(`inbox-${width}.png`),
      animations: "disabled",
    });
    if (width < 1024) {
      const back = page.getByRole("button", { name: "Volver a conversaciones" });
      const size = await back.boundingBox();
      expect(size!.width).toBeGreaterThanOrEqual(44);
      expect(size!.height).toBeGreaterThanOrEqual(44);
      await back.click();
      await expect(page.getByRole("button", { name: /Consulta en vivo/ })).toBeVisible();
      await expect(page.getByLabel(searchLabel)).toBeFocused();
    }
  });
}

test("legacy assistant messages remain neutral rather than inventing an agent author", async ({
  page,
}) => {
  const state = await fixture(page);
  state.messages.push({ ...message(2, "assistant"), author_type: "unknown" });
  await page.goto("/inbox");
  await page.getByRole("button", { name: /Consulta en vivo/ }).click();
  await expect(page.getByRole("log").getByText("SaltaCode", { exact: true })).toBeVisible();
  await expect(page.getByRole("log").getByText("Agente", { exact: true })).toHaveCount(0);
});
