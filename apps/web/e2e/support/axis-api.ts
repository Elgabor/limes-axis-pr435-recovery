import { expect, type APIRequestContext, type Page } from "@playwright/test";

/*
 * Shared seams for live console lanes against the real local Axis stack.
 *
 * Hygiene contract: the API is intentionally append-only (no DELETE routes),
 * so nothing here deletes demo-tenant records. Every helper derives
 * collision-free, project-scoped identifiers from the Playwright project name
 * plus a run token, so the three parallel browser projects can never race on
 * the same records or mutate each other's state. Residual rows stay visible
 * through their `e2e` prefixes and are documented as local-only test data.
 */

export const DEMO_TENANT_ID = "tenant_demo_manufacturing";

export const AXIS_API_BASE_URL =
  process.env.AXIS_E2E_API_BASE_URL ?? "http://127.0.0.1:8000";

/**
 * Collision-free identifier fragment for one lane run: project name plus a
 * time-and-random token. Safe for connector ids, display names and idempotency
 * keys; stays within the API's 160-char connector id column.
 */
export function scopedRunToken(projectName: string): string {
  const project = projectName.replace(/[^a-z0-9]+/gi, "").toLowerCase();
  const token = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  return `${project}_${token}`;
}

/** Register one CSV manifest through the real operations API (demo mode). */
export async function registerCsvManifest(
  request: APIRequestContext,
  input: {
    connectorId: string;
    displayName: string;
    tenantId?: string;
    /** Live-capable manifests pass the API's live-enablement preconditions. */
    liveCapable?: boolean;
  },
): Promise<{ ok: boolean; status: number }> {
  const response = await request.post(
    `${AXIS_API_BASE_URL}/operations/connectors/manifests`,
    {
      data: {
        tenant_id: input.tenantId ?? DEMO_TENANT_ID,
        registered_by: "platform-connector-owner-role",
        manifest: {
          connector_id: input.connectorId,
          display_name: input.displayName,
          connector_type: "file_csv",
          version: "2026-08-22",
          source_type: "csv_upload",
          sync_modes: input.liveCapable
            ? ["schema_preview", "manual_import", "live_query"]
            : ["schema_preview", "manual_import"],
          runtime_boundary: "axis-connector-sandbox",
          required_permissions: ["connectors:read", "connectors:file_csv:preview"],
          credential_requirements: {
            storage: "not_required",
            required_secret_refs: [],
            notes: ["Local e2e fixture; no credentials referenced."],
          },
          schema_fields: [
            {
              source_column: "asset_id",
              target_field: "node_id",
              ontology_target: "manufacturing_asset",
              data_type: "string",
              required: true,
              description: "Stable asset identifier.",
            },
          ],
          mapping_notes: ["Registered by an automated local console lane."],
        },
        runtime_policy: {
          allowed_operations: input.liveCapable
            ? ["schema_validate", "metadata_preview", "live_query", "external_egress"]
            : ["schema_validate", "metadata_preview"],
          blocked_operations: input.liveCapable
            ? ["live_write", "credential_capture"]
            : [
                "live_query",
                "live_write",
                "credential_capture",
                "external_egress",
              ],
          egress_policy: input.liveCapable
            ? "allowlisted-private-egress-with-policy-evidence"
            : "no-external-egress",
          max_file_size_mb: 5,
          row_limit: 100,
          payload_policy: input.liveCapable
            ? "metadata-and-row-digest-redacted-live-query"
            : "metadata-only-redacted-preview",
        },
        preview_sample: {
          file_name: "e2e-assets.csv",
          record_count: 1,
          headers: ["asset_id"],
          sample_rows: [{ asset_id: "asset_e2e_001" }],
        },
        notes: [`Created by the ${input.connectorId} console lane.`],
      },
    },
  );
  return { ok: response.ok(), status: response.status() };
}

/**
 * Drive one governed lifecycle transition through the real API. Returns the
 * JSON detail envelope (`reason`, `request_id`) on failure so lanes can assert
 * exact denial classes instead of guessing.
 */
export async function transitionManifestLifecycle(
  request: APIRequestContext,
  input: {
    connectorId: string;
    targetStatus: string;
    actorScopes: string[];
    evidenceRefs?: string[];
    tenantId?: string;
  },
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await request.post(
    `${AXIS_API_BASE_URL}/operations/connectors/manifests/${encodeURIComponent(input.connectorId)}/lifecycle`,
    {
      data: {
        tenant_id: input.tenantId ?? DEMO_TENANT_ID,
        transitioned_by: "platform-connector-owner-role",
        target_status: input.targetStatus,
        actor_scopes: input.actorScopes,
        transition_reason: "Recorded by an automated local console lane.",
        evidence_refs: input.evidenceRefs ?? [],
      },
    },
  );
  return { status: response.status(), body: (await response.json()) as Record<string, unknown> };
}

/** Read the current manifest detail envelope for one connector. */
export async function fetchManifestDetail(
  request: APIRequestContext,
  connectorId: string,
  tenantId: string = DEMO_TENANT_ID,
): Promise<Record<string, unknown> | null> {
  const response = await request.get(
    `${AXIS_API_BASE_URL}/operations/connectors/manifests/${encodeURIComponent(connectorId)}`,
    { params: { tenant_id: tenantId } },
  );
  if (!response.ok()) {
    return null;
  }
  return (await response.json()) as Record<string, unknown>;
}

/** Open the console page whose URL state selects one connector's detail pane. */
export async function openConnectorDetail(page: Page, displayName: string): Promise<void> {
  await page.goto("/connectors");
  await expect(
    page.getByRole("heading", { name: "Connectors", exact: true }),
  ).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: displayName }).click();
}
