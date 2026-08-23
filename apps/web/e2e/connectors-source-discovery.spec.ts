import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow } from "./support/console-layout";
import {
  AXIS_API_BASE_URL,
  DEMO_TENANT_ID,
  scopedRunToken,
} from "./support/axis-api";
import { createSourceTables, seedGovernanceRecords, SOURCE_SCHEMA } from "./support/source-lane";

/*
 * Real source discovery journey against the live local stack: the console's
 * external-DB connector verifies connectivity and runs bounded schema
 * discovery against a throwaway Postgres schema on the same Docker source
 * database the API is configured with (AXIS_EXTERNAL_DB_LIVE_QUERY_DSN).
 *
 * Table creation and governance seeding live in support/source-lane.ts, shared
 * with the activation lane. The demo deployment has no OIDC principal, so UI
 * writes run through the demo-mode scope convention; the missing-scope denial
 * is proven at the API level below instead of being fabricated in the browser.
 */

test.describe("Axis live story: connector source discovery", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API runs with source discovery enabled.",
  );

  test("verifies and discovers a real source into catalog evidence", async ({ page }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const tableNames = createSourceTables(token);
    const { leaseId, policyId } = await seedGovernanceRecords(page.request, token);

    await page.goto("/connectors");
    await page.getByRole("button", { name: /Postgres operational mirror/ }).click();
    await expect(
      page.getByRole("heading", { name: /Postgres operational mirror/ }),
    ).toBeVisible();

    const panel = page.getByRole("region", { name: "Verify & discover" });
    await expect(panel).toBeVisible();
    // Both prerequisites resolve from real persisted tenant records, and the
    // reference inputs arrive prefilled with them.
    await expect(panel.getByText("Ready")).toHaveCount(2);
    await expect(panel.getByLabel("Credential lease ID")).toHaveValue(/.+/);
    await expect(panel.getByLabel("Egress policy ID")).not.toHaveValue("");

    // This lane seeds its own governance records; point the references at
    // them so the API resolves exactly the evidence this run created.
    await panel.getByLabel("Credential lease ID").fill(leaseId);
    await panel.getByLabel("Egress policy ID").fill(policyId);

    await panel.getByRole("button", { name: "Verify connection" }).click();
    await expect(
      panel.getByText(/Connected read-only to database/),
    ).toBeVisible({ timeout: 15_000 });

    await panel.getByLabel("Schema to discover").fill(SOURCE_SCHEMA);
    await panel.getByRole("button", { name: "Discover tables" }).click();
    const resultsTable = panel.getByRole("table");
    await expect(resultsTable).toBeVisible({ timeout: 15_000 });
    for (const tableName of tableNames) {
      // The qualified resource name is unique to the table column; column
      // names embed the table prefix, so a bare text match would be ambiguous.
      await expect(
        resultsTable.getByRole("cell", { name: new RegExp(`^${SOURCE_SCHEMA}\\.${tableName}`) }),
      ).toBeVisible();
    }
    // Every discovered row carries an evidence-derived drift pill. Which
    // state appears depends on whether a parallel lane observed these
    // tables first (honest concurrent-observer semantics); the strict
    // added→changed→unchanged transitions are proven by the API suites.
    const driftPills = resultsTable.locator(".status-pill");
    await expect(driftPills.first()).toBeVisible();
    for (const pill of await driftPills.all()) {
      expect(await pill.textContent()).toMatch(/^(New|Changed|Unchanged)$/);
    }

    // Discovery results must not push the layout sideways at any width.
    await expectNoHorizontalOverflow(page);
    expect(pageErrors).toEqual([]);

    // The catalog read model reflects the same observations through the
    // data-assets surface, proving the evidence crossed the boundary.
    const resources = await page.request.get(
      `${AXIS_API_BASE_URL}/data/assets/source:external_db_operational_mirror:default/resources?tenant_id=${DEMO_TENANT_ID}`,
    );
    expect(resources.ok()).toBeTruthy();
    const resourcesBody = await resources.json();
    for (const tableName of tableNames) {
      const resource = resourcesBody.resources.find(
        (entry: { resource_name: string }) =>
          entry.resource_name === `${SOURCE_SCHEMA}.${tableName}`,
      );
      expect(resource, `${SOURCE_SCHEMA}.${tableName} in catalog`).toBeTruthy();
      expect(resource.last_source_kind).toBe("postgres_discovery");
      expect(resource.observation_count).toBeGreaterThanOrEqual(1);
      expect(["added", "changed", "unchanged"]).toContain(resource.drift_state);
    }
  });

  test("keeps discovered resources out of other tenants' catalogs", async ({ request }) => {
    // Cross-tenant catalog reads fail closed: any other tenant scope is not
    // part of this connector's registry, so the API refuses instead of
    // listing (or even proving existence of) the discovered resources.
    const response = await request.get(
      `${AXIS_API_BASE_URL}/data/assets/source:external_db_operational_mirror:default/resources`,
      { params: { tenant_id: "tenant_e2e_not_onboarded" } },
    );
    expect([403, 404]).toContain(response.status());
    const body = await response.text();
    expect(body).not.toContain(SOURCE_SCHEMA);
    expect(body).not.toContain("production_orders_");
  });

  test("rejects discovery without the source discovery scope", async ({ request }) => {
    const response = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/discover`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          discovery_id: "discovery_e2e_denied_001",
          requested_by: "connector-console-operator",
          connection_profile_id: "profile_postgres_discovery_readonly",
          schema_name: SOURCE_SCHEMA,
          credential_lease_id: "lease_does_not_matter",
          egress_policy_id: "policy_does_not_matter",
          actor_scopes: [],
        },
      },
    );

    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.detail.reason).toBe("missing_scope:connectors:source:discover");
    expect(body.detail.required_permission).toBe("connectors:source:discover");
  });
});
