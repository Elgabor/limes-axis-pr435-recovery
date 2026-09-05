import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

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
 * Rendered-proof capture lane for the governed source ingestion journey.
 * Opt-in only (AXIS_E2E_CAPTURE_SCREENSHOTS=1) so canonical runs never rewrite
 * documentation assets as a side effect. Every pixel comes from the real
 * journey against the live local stack — no mocked states are captured, and
 * the validation-only contract is visible in every relevant frame.
 */

// Anchored to this file's location, never to a process CWD, so captures can
// only ever land inside the repository's docs/screenshots directory.
const SHOT_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "docs",
  "screenshots",
  "connectors-source-ingestion-2026-08-23",
);

test.describe("Axis rendered proof: governed source ingestion", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1"
      || process.env.AXIS_E2E_CAPTURE_SCREENSHOTS !== "1",
    "Set AXIS_E2E_LIVE_API=1 and AXIS_E2E_CAPTURE_SCREENSHOTS=1 to recapture.",
  );

  const isMobileProject = (projectName: string) => projectName !== "chromium";

  async function openIngestionPanelWithEligibleBinding(
    page: Page,
    token: string,
  ): Promise<{ resourceName: string }> {
    createSourceTables(token);
    const governance = await seedGovernanceRecords(page.request, token);
    const resourceName = `${SOURCE_SCHEMA}.production_orders_${token}`;
    const fingerprints = await discoverSourceTables(page.request, {
      token,
      discoveryId: `discovery_e2e_ingest_shot_${token}`,
      leaseId: governance.leaseId,
      policyId: governance.policyId,
    });
    const fingerprint = fingerprints.get(resourceName);
    expect(fingerprint).toBeTruthy();
    const activated = await page.request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-bindings`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          activation_id: `activation_e2e_ingest_shot_${token}`,
          requested_by: "connector-console-operator",
          connection_profile_id: "profile_postgres_discovery_readonly",
          credential_lease_id: governance.leaseId,
          egress_policy_id: governance.policyId,
          activation_reason: `Rendered proof ${token}: bind reviewed schema.`,
          selections: [
            {
              binding_id: `binding_e2e_ingestion_${token}`,
              resource_name: resourceName,
              expected_schema_fingerprint: fingerprint!,
            },
          ],
          actor_scopes: ["connectors:source:activate"],
        },
      },
    );
    expect(activated.status(), await activated.text()).toBe(200);

    await page.goto("/connectors");
    await page.getByRole("button", { name: /Postgres operational mirror/ }).click();
    await expect(
      page.getByRole("table", { name: "Active source bindings" }),
    ).toBeVisible({ timeout: 15_000 });
    return { resourceName };
  }

  test("captures the ingestion journey states", async ({ page }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const prefix = isMobileProject(testInfo.project.name) ? "mobile" : "desktop";
    const shot = (name: string) => `${SHOT_DIR}/${prefix}-${name}.png`;

    const { resourceName } = await openIngestionPanelWithEligibleBinding(page, token);

    // State 1: honest eligibility plus the validation-only contract.
    const eligibilityTable = page.getByRole("table", { name: "Ingestion eligibility" });
    const eligibleRow = eligibilityTable.getByRole("row", {
      name: new RegExp(resourceName.replace(/\./g, "\\.")),
    });
    await expect(eligibleRow.getByText("Eligible")).toBeVisible();
    await page.screenshot({ path: shot("01-eligibility-validation-only"), fullPage: true });

    // State 2: keyboard selection with the required governance reason gating
    // submission while the control says so.
    const checkbox = page.getByRole("checkbox", { name: `Select: ${resourceName}` });
    await checkbox.focus();
    await page.keyboard.press("Space");
    const submit = page.getByRole("button", { name: "Request ingestion" });
    await expect(submit).toBeDisabled();
    await checkbox.focus();
    await page.screenshot({
      path: shot("02-keyboard-selection-reason-required"),
      fullPage: true,
    });

    // State 3: pending submission. Delay-only interception keeps every pixel
    // sourced from the real API exchange.
    await page.route("**/operations/connectors/external-db/source-ingestion-requests*", async (route) => {
      if (route.request().method() === "POST") {
        await new Promise((resolve) => setTimeout(resolve, 1200));
      }
      await route.continue();
    });
    await page.getByLabel("Request ID").fill(`ingreq_e2e_${token}_shot`);
    await page.getByLabel("Governance reason").fill(
      `Rendered proof ${token}: validate bound schema before extraction review.`,
    );
    await submit.click();
    await expect(page.getByRole("button", { name: "Requesting ingestion…" })).toBeVisible();
    await page.screenshot({ path: shot("03-pending-request"), fullPage: true });

    // State 4: durable outcome — queued request in server truth, still honest
    // about validation being the only stage that ran.
    await expect(
      page.getByText("Ingestion request accepted and queued for validation."),
    ).toBeVisible({ timeout: 15_000 });
    const requestsTable = page.getByRole("table", { name: "Governed ingestion requests" });
    await expect(
      requestsTable.getByRole("row", { name: new RegExp(`ingreq_e2e_${token}_shot`) }),
    ).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: shot("04-request-durable-pending-dispatch"), fullPage: true });

    if (!isMobileProject(testInfo.project.name)) {
      // State 5 (desktop): truthful stale evidence after real drift plus a
      // concurrent discovery refresh — the row reads Stale fingerprint and no
      // longer offers a selection control.
      addColumnToSourceTable(`production_orders_${token}`);
      const governance = await seedGovernanceRecords(page.request, `${token}drift`);
      await discoverSourceTables(page.request, {
        token: `${token}drift`,
        discoveryId: `discovery_e2e_ingest_shot_drift_${token}`,
        leaseId: governance.leaseId,
        policyId: governance.policyId,
      });
      await page.reload();
      await page.getByRole("button", { name: /Postgres operational mirror/ }).click();
      const driftedRow = page
        .getByRole("table", { name: "Ingestion eligibility" })
        .getByRole("row", { name: new RegExp(resourceName.replace(/\./g, "\\.")) });
      await expect(driftedRow.getByText("Stale fingerprint")).toBeVisible({
        timeout: 15_000,
      });
      await page.screenshot({ path: shot("05-stale-fingerprint-blocked"), fullPage: true });

      // State 6: reload durability of the earlier request beside fresh state.
      await expect(
        page
          .getByRole("table", { name: "Governed ingestion requests" })
          .getByRole("row", { name: new RegExp(`ingreq_e2e_${token}_shot`) }),
      ).toBeVisible();
    }
  });
});
