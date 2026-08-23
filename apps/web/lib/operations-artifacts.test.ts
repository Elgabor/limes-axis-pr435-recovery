import { describe, expect, it } from "vitest";

import type {
  IdentitySessionReadModel,
  ManufacturingOperationsSnapshot,
} from "./platform-overview";
import {
  buildOperationsArtifactRequest,
  getOperationsArtifactActionState,
  OPERATIONS_ARTIFACT_ACTIONS,
  OperationsArtifactRequestError,
} from "./operations-artifacts";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

const verifiedSession: IdentitySessionReadModel = {
  authenticated: true,
  mode: "bearer_token",
  actor_id: "plant-operations-owner",
  tenant_id: "tenant_demo_manufacturing",
  scopes: [
    "audit:read",
    "briefs:generate",
    "maintenance:read",
    "quality:read",
    "supply:read",
    "workflows:read",
  ],
  expires_at: 1_785_000_000,
  api_auth_required: true,
  enterprise_sso_ready: true,
  readiness_status: "ready",
  issuer: "https://identity.example.test/realms/axis",
  audience: "limes-axis-api",
  jwks_source: "configured_jwks",
  session_boundary: "bearer_token_verified_by_axis_api",
  capabilities: ["API-verified actor and tenant binding."],
  limitations: [],
  notes: [],
  unauthenticated_reason: null,
};

const operationsSnapshot: ManufacturingOperationsSnapshot = {
  tenant_id: "tenant_demo_manufacturing",
  plant_name: "Ravenna Works",
  scenario: "Plant Operations Cockpit",
  provenance: "live",
  as_of: "2026-06-22T09:00:00+02:00",
  metrics: [],
  domain_snapshots: [],
  latest_daily_briefs: [],
  risk_scenarios: [],
  active_workflows: [],
  pending_approvals: [],
  recent_audit_events: [],
  generation_boundary: "persisted_operations_snapshot",
  notes: [],
};

describe("operations artifacts", () => {
  it("declares only API-backed operations actions with required scopes", () => {
    expect(OPERATIONS_ARTIFACT_ACTIONS.map((action) => action.kind)).toEqual([
      "daily_brief",
      "quality_risk",
      "maintenance_risk",
      "supplier_delay",
    ]);
    expect(
      OPERATIONS_ARTIFACT_ACTIONS.every(
        (action) => action.endpoint.startsWith(`${OPERATIONS_API_PREFIX}/operations/`)
          && action.requiredScopes.includes("audit:read")
          && action.requiredScopes.includes("workflows:read"),
      ),
    ).toBe(true);
  });

  it("builds a deterministic daily brief request from the API-verified session", () => {
    const request = buildOperationsArtifactRequest({
      kind: "daily_brief",
      identitySession: verifiedSession,
      snapshot: operationsSnapshot,
    });

    expect(request.endpoint).toBe(`${OPERATIONS_API_PREFIX}/operations/daily-brief`);
    expect(request.body).toEqual({
      tenant_id: "tenant_demo_manufacturing",
      brief_date: "2026-06-22",
      requested_by: "plant-operations-owner",
      actor_scopes: verifiedSession.scopes,
      idempotency_key:
        "tenant_demo_manufacturing:console:daily_brief:2026-06-22:plant-operations-owner",
      limit: 100,
    });
  });

  it("builds deterministic risk scenario requests without browser-made actor scopes", () => {
    const request = buildOperationsArtifactRequest({
      kind: "quality_risk",
      identitySession: verifiedSession,
      snapshot: operationsSnapshot,
    });

    expect(request.endpoint).toBe(`${OPERATIONS_API_PREFIX}/operations/risk-scenarios/quality`);
    expect(request.body.requested_by).toBe(verifiedSession.actor_id);
    expect(request.body.actor_scopes).toBe(verifiedSession.scopes);
    expect(request.body.idempotency_key).toBe(
      "tenant_demo_manufacturing:console:quality_risk:current:plant-operations-owner",
    );
  });

  it("blocks artifact generation when the session is not API authenticated", () => {
    const publicSession: IdentitySessionReadModel = {
      ...verifiedSession,
      authenticated: false,
      actor_id: null,
      tenant_id: null,
      scopes: [],
      session_boundary: "no_authenticated_api_actor",
    };

    expect(() =>
      buildOperationsArtifactRequest({
        kind: "daily_brief",
        identitySession: publicSession,
        snapshot: operationsSnapshot,
      }),
    ).toThrow(OperationsArtifactRequestError);
    expect(
      getOperationsArtifactActionState("daily_brief", publicSession).canRun,
    ).toBe(false);
  });

  it("reports missing scopes before a mutation can be submitted", () => {
    const limitedSession: IdentitySessionReadModel = {
      ...verifiedSession,
      scopes: ["audit:read", "workflows:read"],
    };

    const state = getOperationsArtifactActionState("supplier_delay", limitedSession);

    expect(state.canRun).toBe(false);
    expect(state.missingScopes).toEqual(["supply:read"]);
    expect(() =>
      buildOperationsArtifactRequest({
        kind: "supplier_delay",
        identitySession: limitedSession,
        snapshot: operationsSnapshot,
      }),
    ).toThrow("Missing required scopes: supply:read");
  });
});
