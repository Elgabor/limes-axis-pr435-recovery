import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow } from "./support/console-layout";
import {
  AXIS_API_BASE_URL,
  DEMO_TENANT_ID,
  scopedRunToken,
} from "./support/axis-api";
import {
  addColumnToSourceTable,
  createSourceTables,
  discoverSourceTables,
  seedGovernanceRecords,
  SOURCE_SCHEMA,
} from "./support/source-lane";

/*
 * Governed source activation journey against the live local stack: discover a
 * real throwaway schema, select tables in the console, activate them into
 * durable bindings, and prove the bindings survive reloads. Every state the
 * browser shows comes from the real API — the only interception below delays
 * one request so the pending state is observable; it never fakes a response.
 *
 * Binding ids persist under their `_e2e_activation_` prefix per the
 * append-only hygiene contract documented in support/source-lane.ts.
 */

test.describe("Axis live story: governed source activation", () => {
  // Same-project journeys share one tokenized-table namespace and one
  // console tenant; running them concurrently would let one journey's
  // seeding/cleanup interfere with the other's discovery evidence.
  test.describe.configure({ mode: "serial" });

  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API runs with source discovery enabled.",
  );

  async function openDiscoveryResults(
    page: Page,
    token: string,
  ): Promise<{ leaseId: string; policyId: string }> {
    createSourceTables(token);
    const governance = await seedGovernanceRecords(page.request, token);

    await page.goto("/connectors");
    await page.getByRole("button", { name: /Postgres operational mirror/ }).click();
    const panel = page.getByRole("region", { name: "Verify & discover" });
    await expect(panel).toBeVisible();
    // Prerequisites are legible before anything runs, resolved from real
    // persisted tenant records.
    await expect(panel.getByText("Ready")).toHaveCount(2);
    await panel.getByLabel("Credential lease ID").fill(governance.leaseId);
    await panel.getByLabel("Egress policy ID").fill(governance.policyId);

    await panel.getByRole("button", { name: "Verify connection" }).click();
    await expect(
      panel.getByText(/Connected read-only to database/),
    ).toBeVisible({ timeout: 15_000 });

    await panel.getByLabel("Schema to discover").fill(SOURCE_SCHEMA);
    await panel.getByRole("button", { name: "Discover tables" }).click();
    await expect(panel.getByRole("table")).toBeVisible({ timeout: 15_000 });
    return governance;
  }

  function ordersCheckbox(page: Page, token: string) {
    // Anchor on this run's tokenized table so parallel projects (which
    // legitimately discover their own identically-prefixed tables) never
    // turn the locator ambiguous.
    return page.getByRole("checkbox", {
      name: `Activate: ${SOURCE_SCHEMA}.production_orders_${token}`,
    });
  }

  async function activateFirstTableByKeyboard(
    page: Page,
    token: string,
    reason: string,
  ): Promise<void> {
    // Keyboard-first selection: focus the row checkbox and toggle with Space.
    const checkbox = ordersCheckbox(page, token);
    await checkbox.focus();
    await expect(checkbox).toBeFocused();
    await page.keyboard.press("Space");
    await expect(page.getByText("1 table selected")).toBeVisible();

    const activate = page.getByRole("button", { name: "Activate 1 table" });
    // The governance reason is required; the control says so while blocked.
    await expect(activate).toBeDisabled();
    await page.getByLabel("Activation reason").fill(reason);
    await expect(activate).toBeEnabled();
  }


  test("activates a discovered table and proves the binding durable", async ({
    page,
  }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const { leaseId, policyId } = await openDiscoveryResults(page, token);

    // Delay-only interception: the response still comes from the real API;
    // the pause just makes the honest pending state observable.
    await page.route("**/operations/connectors/external-db/source-bindings*", async (route) => {
      if (route.request().method() === "POST") {
        await new Promise((resolve) => setTimeout(resolve, 900));
      }
      await route.continue();
    });

    await test.step("select and activate one discovered table", async () => {
      await activateFirstTableByKeyboard(
        page,
        token,
        `Console activation lane ${token}: bind reviewed schema for ingestion.`,
      );
      await page.getByRole("button", { name: "Activate 1 table" }).click();
    });

    // Pending: the action button names what is happening and blocks repeats.
    const activating = page.getByRole("button", { name: "Activating…" });
    await expect(activating).toBeVisible();
    await expect(activating).toBeDisabled();

    // Success never claims data moved: the binding is active for governance
    // and explicitly pending ingestion.
    await expect(
      page.getByText(/Activated 1 binding/).first(),
    ).toBeVisible({ timeout: 15_000 });

    const bindingsSection = page.getByRole("region", { name: "Active source bindings" });
    const bindingsTable = bindingsSection.getByRole("table");
    await expect(bindingsTable).toBeVisible({ timeout: 15_000 });
    const bindingRow = bindingsTable.getByRole("row", {
      name: new RegExp(`${SOURCE_SCHEMA}\\.production_orders_${token}`),
    });
    await expect(bindingRow).toBeVisible();
    await expect(bindingRow.getByText("Active")).toBeVisible();
    await expect(bindingRow.getByText("Pending ingestion")).toBeVisible();

    // The completed journey resets instead of offering already-bound tables.
    await expect(ordersCheckbox(page, token)).toHaveCount(0);
    // And nowhere does the console claim a sync happened.
    const sectionText = (await bindingsSection.textContent()) ?? "";
    expect(sectionText).not.toMatch(/\bsynced\b|synchron/i);

    // Durability is proven by reload: the binding list is server truth.
    await page.reload();
    const reloadedBindings = page.getByRole("region", { name: "Active source bindings" });
    await expect(reloadedBindings.getByRole("table")).toBeVisible({ timeout: 15_000 });
    await expect(
      reloadedBindings.getByRole("row", {
        name: new RegExp(`${SOURCE_SCHEMA}\\.production_orders_${token}`),
      }),
    ).toBeVisible();

    // Same-tenant replay through the API: resubmitting the identical binding
    // returns the existing row as `replayed` instead of duplicating it.
    const listed = await page.request.get(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-bindings`,
      { params: { tenant_id: DEMO_TENANT_ID, connector_id: "external_db_operational_mirror" } },
    );
    expect(listed.ok()).toBeTruthy();
    const listedBody = (await listed.json()) as {
      bindings: Array<{
        binding_id: string;
        resource_name: string;
        schema_fingerprint: string;
        connection_profile_id: string;
      }>;
    };
    const binding = listedBody.bindings.find(
      (entry) => entry.resource_name === `${SOURCE_SCHEMA}.production_orders_${token}`,
    );
    expect(binding, "activated binding persisted").toBeTruthy();

    const replay = await page.request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-bindings`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          activation_id: `activation_e2e_replay_${token}`,
          requested_by: "connector-console-operator",
          connection_profile_id: binding!.connection_profile_id,
          credential_lease_id: leaseId,
          egress_policy_id: policyId,
          activation_reason: `Replay proof for ${token}`,
          selections: [
            {
              binding_id: binding!.binding_id,
              resource_name: binding!.resource_name,
              expected_schema_fingerprint: binding!.schema_fingerprint,
            },
          ],
          actor_scopes: ["connectors:source:activate"],
        },
      },
    );
    expect(replay.status(), await replay.text()).toBe(200);
    const replayBody = (await replay.json()) as {
      bindings: Array<{ outcome: string; binding_id: string }>;
    };
    expect(replayBody.bindings.map((entry) => entry.outcome)).toEqual(["replayed"]);
    expect(replayBody.bindings[0].binding_id).toBe(binding!.binding_id);

    await expectNoHorizontalOverflow(page);
    expect(pageErrors).toEqual([]);
  });

  test("recovers from stale source drift with honest copy", async ({
    page,
  }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const { leaseId, policyId } = await openDiscoveryResults(page, token);

    // Real drift happens at the source AFTER this page's discovery, on the
    // very table about to be activated. Drift alone changes nothing in Axis;
    // a CONCURRENT discovery run (here: through the real API) refreshes the
    // persisted observations. This page still holds the pre-drift
    // fingerprints it reviewed, so its next activation is stale by design.
    addColumnToSourceTable(`production_orders_${token}`);
    const refreshed = await discoverSourceTables(page.request, {
      token,
      discoveryId: `discovery_e2e_drift_${token}`,
      leaseId,
      policyId,
    });
    expect(refreshed.get(`${SOURCE_SCHEMA}.production_orders_${token}`)).toBeDefined();

    await test.step("select drifted table and attempt activation", async () => {
      await activateFirstTableByKeyboard(page, token, `Stale drift lane ${token}`);
      await page.getByRole("button", { name: "Activate 1 table" }).click();
    });
    void policyId;

    const panel = page.getByRole("region", { name: "Verify & discover" });
    await test.step("expect honest stale copy", async () => {
      await expect(
        panel.getByText(/changed since it was discovered/i),
      ).toBeVisible({ timeout: 15_000 });
    });
    // Nothing for THIS run was bound behind the operator's back (earlier
    // serial journeys may legitimately own other rows in the shared tenant).
    const bindingsSection = page.getByRole("region", { name: "Active source bindings" });
    await expect(
      bindingsSection.getByRole("cell", {
        name: new RegExp(`^${SOURCE_SCHEMA}\\.production_orders_${token}$`),
      }),
    ).toHaveCount(0);

    // Recovery path named by the error copy: run discovery again.
    await panel.getByLabel("Schema to discover").fill(SOURCE_SCHEMA);
    await panel.getByRole("button", { name: "Discover tables" }).click();
    // Wait for the REFRESHED evidence, not just any table: the drifted table
    // now lists the column the concurrent drift added.
    await expect(
      panel
        .getByRole("row", { name: new RegExp(`${SOURCE_SCHEMA}\\.production_orders_${token}`) })
        .getByText("severity"),
    ).toBeVisible({ timeout: 15_000 });
    // Rediscovery resets the earlier selection honestly.
    await expect(ordersCheckbox(page, token)).not.toBeChecked();
    // Rediscovery resets the previous selection honestly...
    await test.step("re-select after rediscovery", async () => {
      const box = ordersCheckbox(page, token);
      await box.focus();
      await expect(box).toBeFocused();
      await page.keyboard.press("Space");
      await expect(page.getByText("1 table selected")).toBeVisible();
    });
    await page.getByLabel("Activation reason").fill(`Recovered activation ${token}`);
    await page.getByRole("button", { name: "Activate 1 table" }).click();

    const bindingsTable = bindingsSection.getByRole("table");
    await expect(bindingsTable).toBeVisible({ timeout: 15_000 });
    // ...and the fresh evidence activates cleanly.
    await expect(
      bindingsTable.getByRole("row", {
        name: new RegExp(`${SOURCE_SCHEMA}\\.production_orders_${token}`),
      }),
    ).toBeVisible();
  });

  test("rejects activation without the source activation scope", async ({ request }) => {
    const response = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-bindings`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          activation_id: "activation_e2e_denied_001",
          requested_by: "connector-console-operator",
          connection_profile_id: "profile_postgres_discovery_readonly",
          credential_lease_id: "lease_does_not_matter",
          egress_policy_id: "policy_does_not_matter",
          activation_reason: "Scope denial proof.",
          selections: [
            {
              binding_id: "binding_e2e_denied_001",
              resource_name: `${SOURCE_SCHEMA}.whatever`,
              expected_schema_fingerprint: "a".repeat(64),
            },
          ],
          actor_scopes: [],
        },
      },
    );

    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.detail.reason).toBe("missing_scope:connectors:source:activate");
    expect(body.detail.required_permission).toBe("connectors:source:activate");
  });
});
