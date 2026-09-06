import { expect, test } from "@playwright/test";

import {
  AXIS_API_BASE_URL,
  DEMO_TENANT_ID,
  fetchManifestDetail,
  registerCsvManifest,
  scopedRunToken,
  transitionManifestLifecycle,
} from "./support/axis-api";

/*
 * Isolated-tenant onboarding journey (API-driven).
 *
 * The console pins unauthenticated demo traffic to the public demo tenant, so
 * a genuinely fresh tenant cannot be reached through the browser UI without an
 * authenticated session for that tenant (the SSO lane covers that boundary
 * separately). What CAN be proven end-to-end here is the server-side journey
 * the checklist step derives from: bootstrap a throwaway tenant with zero
 * connectors, register a manifest, prove the connect step is still open while
 * the manifest is only registered, activate it, and prove the step closes —
 * plus reload persistence and tenant isolation. Tenant ids are unique per run,
 * so parallel projects never share state and nothing in the demo tenant is
 * touched.
 *
 * Cleanup honesty: the API is append-only (no DELETE routes), so the
 * throwaway tenant rows persist locally. They are quarantined under their
 * unique `tenant_e2e_onb_` prefix and never referenced again.
 */

const ACTIVATION_SCOPES = ["connectors:manifest:lifecycle"];

test.describe("Axis live story: isolated-tenant onboarding", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  test("connect checklist opens only after activation in a throwaway tenant", async ({ request }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const tenantId = `tenant_e2e_onb_${token}`;
    const connectorId = `file_csv_e2e_onb_${token}`;

    // --- Fresh tenant: bootstrapped scenario, zero connectors -------------
    const bootstrap = await request.post(`${AXIS_API_BASE_URL}/demo/bootstrap`, {
      data: {
        tenant_id: tenantId,
        requested_by: "e2e-isolated-onboarding",
        actor_scopes: ["demo:scenario:bootstrap"],
      },
    });
    expect([200, 201]).toContain(bootstrap.status());
    const bootstrapped = await bootstrap.json();
    expect(bootstrapped.tenant_id).toBe(tenantId);
    expect(bootstrapped.bootstrapped).toBe(true);

    const freshConnectors = await request.get(
      `${AXIS_API_BASE_URL}/operations/connectors`,
      { params: { tenant_id: tenantId } },
    );
    expect(freshConnectors.status()).toBe(200);
    const freshRegistry = await freshConnectors.json();
    // Empty-state evidence: no persisted manifests exist yet.
    expect(
      freshRegistry.connectors.filter(
        (connector: { registry_origin: string }) =>
          connector.registry_origin === "persisted_manifest",
      ),
    ).toEqual([]);

    // --- Registration alone must not close the connect step ---------------
    const registration = await registerCsvManifest(request, {
      connectorId,
      displayName: `E2E onboarding ${token}`,
      tenantId,
    });
    expect(registration.status).toBe(201);

    const registeredRegistry = await (
      await request.get(`${AXIS_API_BASE_URL}/operations/connectors`, {
        params: { tenant_id: tenantId },
      })
    ).json();
    const registered = registeredRegistry.connectors.find(
      (connector: { manifest: { connector_id: string } }) =>
        connector.manifest.connector_id === connectorId,
    );
    expect(registered?.persisted_manifest?.status).toBe("registered_preview_only");
    expect(activeCount(registeredRegistry)).toBe(0);

    // --- Activation closes the step ---------------------------------------
    const activation = await transitionManifestLifecycle(request, {
      connectorId,
      targetStatus: "active_preview",
      actorScopes: ACTIVATION_SCOPES,
      tenantId,
    });
    expect(activation.status).toBe(200);
    expect(activation.body.status).toBe("active_preview");

    // Reload persistence through a fresh read: the activated state survives.
    const reloadedRegistry = await (
      await request.get(`${AXIS_API_BASE_URL}/operations/connectors`, {
        params: { tenant_id: tenantId },
      })
    ).json();
    expect(activeCount(reloadedRegistry)).toBe(1);

    // The transition trail records exactly one governed change.
    const detail = await fetchManifestDetail(request, connectorId, tenantId);
    expect(detail).not.toBeNull();
    const transitions = detail?.transitions as Array<Record<string, unknown>>;
    expect(transitions).toHaveLength(1);
    expect(transitions[0].target_status).toBe("active_preview");

    // --- Tenant isolation --------------------------------------------------
    const crossRead = await fetchManifestDetail(request, connectorId, DEMO_TENANT_ID);
    expect(crossRead).toBeNull();
    const demoRegistry = await (
      await request.get(`${AXIS_API_BASE_URL}/operations/connectors`, {
        params: { tenant_id: DEMO_TENANT_ID },
      })
    ).json();
    expect(
      demoRegistry.connectors.some(
        (connector: { manifest: { connector_id: string } }) =>
          connector.manifest.connector_id === connectorId,
      ),
    ).toBe(false);
  });
});

/** Server-side truth behind the onboarding connect step's done state. */
function activeCount(registry: { connectors: Array<{ persisted_manifest: { status: string } | null }> }): number {
  return registry.connectors.filter((connector) =>
    ["active_preview", "active_live"].includes(
      connector.persisted_manifest?.status ?? "",
    ),
  ).length;
}
