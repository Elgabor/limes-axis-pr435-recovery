import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

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
 * Governed source ingestion journey against the live local stack, CONTINUING
 * from durable activated bindings: real tables are created, really discovered,
 * really activated through the API (the same boundary the activation lane
 * drives through the console), and this lane proves the ingestion panel end to
 * end — honest eligibility, required reason, idempotent create/replay, the
 * validation-only contract, durable status after reload, and precise stale
 * semantics after real source drift. No response is ever faked; the only
 * interception below delays one request so a pending state is observable.
 *
 * Hygiene: binding ids persist under `binding_e2e_ingestion_`, request ids
 * under `ingreq_e2e_`, per support/source-lane.ts's append-only contract.
 */

const INGESTION_SCOPE = "connectors:source:ingest";
test.describe("Axis live story: governed source ingestion", () => {
  test.describe.configure({ mode: "serial" });

  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API runs with source discovery enabled.",
  );

  async function bindingForResource(
    request: APIRequestContext,
    resourceName: string,
  ): Promise<{ binding_id: string }> {
    const listed = await request.get(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-bindings`,
      {
        params: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
        },
      },
    );
    expect(listed.ok()).toBeTruthy();
    const body = (await listed.json()) as {
      bindings: Array<{ binding_id: string; resource_name: string }>;
    };
    const binding = body.bindings.find((entry) => entry.resource_name === resourceName);
    expect(binding, `activated binding persisted for ${resourceName}`).toBeTruthy();
    return binding!;
  }

  async function activateThroughApi(
    request: APIRequestContext,
    input: { token: string; leaseId: string; policyId: string; resourceName: string },
  ): Promise<void> {
    const fingerprints = await discoverSourceTables(request, {
      token: input.token,
      discoveryId: `discovery_e2e_ingestion_${input.token}`,
      leaseId: input.leaseId,
      policyId: input.policyId,
    });
    const fingerprint = fingerprints.get(input.resourceName);
    expect(fingerprint, "discovered fingerprint").toBeTruthy();
    const response = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-bindings`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          activation_id: `activation_e2e_ingestion_${input.token}`,
          requested_by: "connector-console-operator",
          connection_profile_id: "profile_postgres_discovery_readonly",
          credential_lease_id: input.leaseId,
          egress_policy_id: input.policyId,
          activation_reason: `Ingestion lane ${input.token}: bind reviewed schema.`,
          selections: [
            {
              binding_id: `binding_e2e_ingestion_${input.token}`,
              resource_name: input.resourceName,
              expected_schema_fingerprint: fingerprint!,
            },
          ],
          actor_scopes: ["connectors:source:activate"],
        },
      },
    );
    expect(response.status(), await response.text()).toBe(200);
    const body = (await response.json()) as { bindings: Array<{ outcome: string }> };
    expect(body.bindings[0].outcome).toBe("activated");
  }

  async function openConnectorDetail(page: Page): Promise<void> {
    await page.goto("/connectors");
    await page.getByRole("button", { name: /Postgres operational mirror/ }).click();
    await expect(
      page.getByRole("table", { name: "Active source bindings" }),
    ).toBeVisible({ timeout: 15_000 });
  }

  test("requests governed validation and proves the request durable", async ({
    page,
  }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const resourceName = `${SOURCE_SCHEMA}.production_orders_${token}`;
    createSourceTables(token);
    const governance = await seedGovernanceRecords(page.request, token);
    await activateThroughApi(page.request, {
      token,
      leaseId: governance.leaseId,
      policyId: governance.policyId,
      resourceName,
    });
    await openConnectorDetail(page);

    const validationOnly = page.getByTestId("source-ingestion-validation-note");
    await expect(validationOnly).toContainText("Validation stage only.");
    await expect(validationOnly).toContainText("No source is dialed and no rows are read");

    // Honest eligibility: our freshly activated table is eligible; nothing
    // here is invented by the console.
    const eligibilityTable = page.getByRole("table", { name: "Ingestion eligibility" });
    const eligibleRow = eligibilityTable.getByRole("row", {
      name: new RegExp(resourceName.replace(/\./g, "\\.")),
    });
    await expect(eligibleRow).toBeVisible();
    await expect(eligibleRow.getByText("Eligible")).toBeVisible();

    // The form appears only when something is eligible, and the required
    // governance reason gates submission while the control says so.
    const submit = page.getByRole("button", { name: "Request ingestion" });
    await expect(submit).toBeDisabled();

    const requestId = `ingreq_e2e_${token}_001`;
    const checkbox = page.getByRole("checkbox", { name: `Select: ${resourceName}` });
    await checkbox.focus();
    await expect(checkbox).toBeFocused();
    await page.keyboard.press("Space");
    await expect(submit).toBeDisabled(); // reason still missing

    await page.getByLabel("Request ID").fill(requestId);
    await page.getByLabel("Governance reason").fill(
      `Console ingestion lane ${token}: validate bound schema before extraction review.`,
    );
    await expect(submit).toBeEnabled();

    // Delay-only interception keeps every pixel sourced from the real API.
    await page.route("**/operations/connectors/external-db/source-ingestion-requests*", async (route) => {
      if (route.request().method() === "POST") {
        await new Promise((resolve) => setTimeout(resolve, 900));
      }
      await route.continue();
    });
    await submit.click();
    await expect(page.getByRole("button", { name: "Requesting ingestion…" })).toBeVisible();
    await expect(submit).toBeDisabled();

    await expect(
      page.getByText("Ingestion request accepted and queued for validation."),
    ).toBeVisible({ timeout: 15_000 });

    const requestsTable = page.getByRole("table", { name: "Governed ingestion requests" });
    const requestRow = requestsTable.getByRole("row", { name: new RegExp(requestId) });
    await expect(requestRow).toBeVisible({ timeout: 15_000 });
    await expect(requestRow.getByText("Pending dispatch")).toBeVisible();
    // The durable list never claims extraction happened.
    const listText = (await requestsTable.textContent()) ?? "";
    expect(listText).not.toMatch(/extracted|rows read|\bsynced\b/i);

    // Durability across reload: the request list is server truth.
    await page.reload();
    await openConnectorDetail(page);
    const reloadedRequests = page.getByRole("table", { name: "Governed ingestion requests" });
    const reloadedRow = reloadedRequests.getByRole("row", { name: new RegExp(requestId) });
    await expect(reloadedRow).toBeVisible({ timeout: 15_000 });

    // Idempotency through the same API boundary: identical ask replays.
    const binding = await bindingForResource(page.request, resourceName);
    const replay = await page.request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          request_id: requestId,
          requested_by: "connector-console-operator",
          reason: `Console ingestion lane ${token}: validate bound schema before extraction review.`,
          selections: [{ binding_id: binding.binding_id }],
          actor_scopes: [INGESTION_SCOPE],
        },
      },
    );
    expect(replay.status(), await replay.text()).toBe(200);
    expect(((await replay.json()) as { outcome: string }).outcome).toBe("replayed");

    // And the same ID with a different ask conflicts instead of overwriting.
    const conflict = await page.request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          request_id: requestId,
          requested_by: "connector-console-operator",
          reason: "A different governance reason entirely.",
          selections: [{ binding_id: binding.binding_id }],
          actor_scopes: [INGESTION_SCOPE],
        },
      },
    );
    expect(conflict.status()).toBe(409);
    expect(((await conflict.json()) as { detail: { reason: string } }).detail.reason).toBe(
      "request_id_conflict",
    );

    await expectNoHorizontalOverflow(page);
    expect(pageErrors).toEqual([]);
  });

  test("marks drifted bindings stale and rejects their new requests", async ({
    page,
  }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const resourceName = `${SOURCE_SCHEMA}.quality_checks_${token}`;
    createSourceTables(token);
    const governance = await seedGovernanceRecords(page.request, token);
    await activateThroughApi(page.request, {
      token,
      leaseId: governance.leaseId,
      policyId: governance.policyId,
      resourceName,
    });

    // Real drift at the source AFTER activation, then a concurrent discovery
    // run refreshes Axis' observations — exactly the production sequence.
    addColumnToSourceTable(token, `quality_checks_${token}`);
    await discoverSourceTables(page.request, {
      token,
      discoveryId: `discovery_e2e_ingest_drift_${token}`,
      leaseId: governance.leaseId,
      policyId: governance.policyId,
    });

    await openConnectorDetail(page);
    const eligibilityTable = page.getByRole("table", { name: "Ingestion eligibility" });
    const staleRow = eligibilityTable.getByRole("row", {
      name: new RegExp(resourceName.replace(/\./g, "\\.")),
    });
    await expect(staleRow).toBeVisible({ timeout: 15_000 });
    await expect(staleRow.getByText("Stale fingerprint")).toBeVisible();
    // Stale rows offer no selection control to submit.
    await expect(
      page.getByRole("checkbox", { name: `Select: ${resourceName}` }),
    ).toHaveCount(0);

    const binding = await bindingForResource(page.request, resourceName);
    const rejected = await page.request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          request_id: `ingreq_e2e_${token}_stale`,
          requested_by: "connector-console-operator",
          reason: `Stale probe ${token}: must fail closed.`,
          selections: [{ binding_id: binding.binding_id }],
          actor_scopes: [INGESTION_SCOPE],
        },
      },
    );
    expect(rejected.status()).toBe(422);
    expect(
      ((await rejected.json()) as { detail: { reason: string } }).detail.reason,
    ).toBe("stale_fingerprint");
  });

  test("extract stage stays disabled and cancel is fenced end to end", async ({
    page,
    request,
  }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const resourceName = `${SOURCE_SCHEMA}.quality_checks_${token}`;
    createSourceTables(token);
    const governance = await seedGovernanceRecords(request, token);
    await activateThroughApi(request, {
      token,
      leaseId: governance.leaseId,
      policyId: governance.policyId,
      resourceName,
    });
    await openConnectorDetail(page);

    // The demo lane API runs with extraction off: the console must not offer
    // the stage, and the API must reject an extract ask with a precise reason.
    await expect(
      page.getByText(/Extraction is enabled here/),
    ).toHaveCount(0);

    const deniedExtract = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          request_id: `ingreq_e2e_${token}_extract`,
          requested_by: "connector-console-operator",
          reason: `Extract gating proof ${token}.`,
          stage: "extract",
          selections: [{ binding_id: `binding_e2e_ingestion_${token}` }],
          actor_scopes: ["connectors:source:ingest"],
        },
      },
    );
    expect(deniedExtract.status()).toBe(422);
    expect(
      ((await deniedExtract.json()) as { detail: { reason: string } }).detail.reason,
    ).toBe("extraction_disabled");

    // Cancel lifecycle through the real API boundary.
    const requestId = `ingreq_e2e_${token}_cancel`;
    const created = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          request_id: requestId,
          requested_by: "connector-console-operator",
          reason: `Cancel lane ${token}.`,
          selections: [{ binding_id: `binding_e2e_ingestion_${token}` }],
          actor_scopes: ["connectors:source:ingest"],
        },
      },
    );
    expect(created.status()).toBe(200);

    const cancelled = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests/${requestId}/cancel`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          cancelled_by: "connector-console-operator",
          reason: `Cancel proof ${token}.`,
          actor_scopes: ["connectors:source:ingest"],
        },
      },
    );
    expect(cancelled.status()).toBe(200);
    expect(((await cancelled.json()) as { status: string }).status).toBe("cancelled");

    // The durable list shows the cancelled state after reload — server truth.
    await page.reload();
    await openConnectorDetail(page);
    const requestsTable = page.getByRole("table", { name: "Governed ingestion requests" });
    await expect(
      requestsTable.getByRole("row", { name: new RegExp(requestId) }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(requestsTable.getByText("Cancelled")).toBeVisible();

    // A conflicting second cancel (different reason) cannot overwrite it.
    const conflict = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests/${requestId}/cancel`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          cancelled_by: "connector-console-operator",
          reason: "Different ask.",
          actor_scopes: ["connectors:source:ingest"],
        },
      },
    );
    expect(conflict.status()).toBe(409);
  });

  test("rejects ingestion without the source ingestion scope", async ({ request }) => {
    const response = await request.post(
      `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-ingestion-requests`,
      {
        data: {
          tenant_id: DEMO_TENANT_ID,
          connector_id: "external_db_operational_mirror",
          request_id: "ingreq_e2e_denied_001",
          requested_by: "connector-console-operator",
          reason: "Scope denial proof.",
          selections: [{ binding_id: "binding_e2e_denied_001" }],
          actor_scopes: [],
        },
      },
    );

    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.detail.reason).toBe(`missing_scope:${INGESTION_SCOPE}`);
    expect(body.detail.required_permission).toBe(INGESTION_SCOPE);
  });
});
