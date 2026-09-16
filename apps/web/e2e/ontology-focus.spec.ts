import { expect, test, type Page } from "@playwright/test";

import type { ManufacturingOntology } from "../lib/ontology-demo";
import { strings } from "../lib/strings";

const api = process.env.AXIS_E2E_API_BASE_URL ?? "http://127.0.0.1:8000";
const endpoint = `${api}/operations/ontology?tenant_id=tenant_demo_manufacturing`;

function entityControls(page: Page, view: "graph" | "list") {
  if (view === "graph") return page.getByTestId("ontology-graph").getByRole("link");
  return (page.viewportSize()?.width ?? 1280) < 640
    ? page.getByLabel("Business objects", { exact: true }).getByRole("button")
    : page.getByRole("table", { name: "Ontology nodes" }).getByRole("button");
}

function explorerHeading(page: Page) {
  return page.getByRole("heading", { name: strings.clarity.ontologyObjects, exact: true });
}

test.describe("ontology entity focus return", () => {
  test.skip(process.env.AXIS_E2E_LIVE_API !== "1", "Requires the isolated local API.");

  for (const view of ["graph", "list"] as const) {
    test(`${view}: keyboard close restores the opener and Tab continues to the next entity`, async ({ page }) => {
      await page.goto(`/ontology?view=${view}`);
      const controls = entityControls(page, view);
      const opener = controls.nth(1);
      await expect(opener).toBeVisible();
      await opener.press("Enter");
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(opener).toBeFocused();
      await expect(page).not.toHaveURL(/entity_id=/);
      await expect(page).toHaveURL(new RegExp(`view=${view}`));
      await page.keyboard.press("Tab");
      await expect(controls.nth(2)).toBeFocused();
    });

    test(`${view}: pointer close and browser history preserve focus without losing the view`, async ({ page }) => {
      await page.goto(`/ontology?view=${view}`);
      const opener = entityControls(page, view).nth(1);
      await expect(opener).toBeVisible();
      const graph = page.getByTestId("ontology-graph");
      const viewBox = view === "graph" ? await graph.getAttribute("viewBox") : null;
      await opener.click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Close", exact: true }).click();
      await expect(dialog).toBeHidden();
      await expect(opener).toBeFocused();

      await opener.press("Enter");
      await expect(dialog).toBeVisible();
      await page.goBack();
      await expect(dialog).toBeHidden();
      await expect(opener).toBeFocused();
      await page.goForward();
      await expect(dialog).toBeVisible();
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      await expect(opener).toBeFocused();
      if (viewBox !== null) await expect(graph).toHaveAttribute("viewBox", viewBox);
    });
  }

  test("direct links have a stable fallback, including a missing entity", async ({ page }) => {
    const response = await page.request.get(endpoint);
    expect(response.ok()).toBe(true);
    const ontology = await response.json() as ManufacturingOntology;
    expect(ontology.nodes.length).toBeGreaterThan(0);

    for (const nodeId of [ontology.nodes[0].node_id, "axis-focus-missing-entity"]) {
      await page.goto(`/ontology?view=list&entity_id=${encodeURIComponent(nodeId)}&context=retained`);
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Close", exact: true }).click();
      await expect(dialog).toBeHidden();
      await expect(explorerHeading(page)).toBeFocused();
      await expect(page).not.toHaveURL(/entity_id=/);
      await expect(page).toHaveURL(/view=list/);
      await expect(page).toHaveURL(/context=retained/);
    }
  });

  test("closing after a responsive view change handles a removed graph opener", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/ontology");
    const opener = entityControls(page, "graph").nth(1);
    await expect(opener).toBeVisible();
    await opener.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("ontology-graph")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(explorerHeading(page)).toBeFocused();
    await expect(page.getByRole("button", { name: "List", exact: true })).toHaveAttribute("aria-pressed", "true");
  });

  test("a connected but CSS-hidden list opener also uses the fallback", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/ontology?view=list");
    const opener = entityControls(page, "list").nth(1);
    await expect(opener).toBeVisible();
    await opener.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(opener).toBeHidden();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(explorerHeading(page)).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Graph", exact: true })).toBeFocused();
  });
});
