import { describe, expect, it } from "vitest";

import { agentRegistryFixture } from "@/components/agents/agents-fixtures";
import {
  connectorRegistryFixture,
  credentialHandleRegistryFixture,
  credentialLeaseRegistryFixture,
  egressPolicyRegistryFixture,
  evidenceInvariantReportFixture,
  manifestDetailFixture,
  manifestRegistryFixture,
  ontologyProposalRegistryFixture,
  runRegistryFixture,
} from "@/components/connector-console/connector-fixtures";
import { ontologyFixture } from "@/components/ontology/ontology-fixtures";
import {
  approvalInboxFixture,
  auditEventsFixture,
  identitySessionFixture,
  modelRoutingFixture,
  overviewFixture,
  policyRegistryFixture,
  snapshotFixture,
} from "@/components/overview/overview-fixtures";

import {
  parseActionRunList,
  parseActionRunPersistenceResult,
  parseManufacturingActionRegistry,
} from "./runtime-contracts/actions";
import {
  parseApprovalDecisionPersistenceResult,
  parseManufacturingApprovalInbox,
} from "./runtime-contracts/approvals";
import { parseAuditExportBundle, parseManufacturingAuditExplorer } from "./runtime-contracts/audit";
import {
  parseAxisReadyReport,
  parseDeploymentReadinessReport,
  parseIdentityBrowserSessionList,
  parseOidcReadinessReport,
  parseSupportDiagnosticsReport,
} from "./runtime-contracts/identity";
import {
  parseConnectorCsvPreviewResult,
  parseConnectorExternalDbPreviewResult,
  parseConnectorManifestDetail,
  parseConnectorRunRecord,
  parseManufacturingConnectorCredentialHandleRegistry,
  parseManufacturingConnectorCredentialLeaseRegistry,
  parseManufacturingConnectorEgressPolicyRegistry,
  parseManufacturingConnectorEvidenceInvariantReport,
  parseManufacturingConnectorEvidenceInvariantSnapshotHistory,
  parseManufacturingConnectorManifestRegistry,
  parseManufacturingConnectorOntologyProposalRegistry,
  parseManufacturingConnectorRegistry,
  parseManufacturingConnectorRunRegistry,
} from "./runtime-contracts/connectors";
import { parseDemoBootstrapResult } from "./runtime-contracts/bootstrap";
import {
  parseIdentitySessionReadModel,
  parseManufacturingNotificationCenter,
  parseManufacturingNotificationAcknowledgementResult,
  parseManufacturingOperationsSnapshot,
  parseManufacturingOverview,
  parseOperationsArtifactResponse,
} from "./runtime-contracts/overview";
import { parseManufacturingAgentRegistry } from "./runtime-contracts/agents";
import { parseManufacturingModelRouting } from "./runtime-contracts/model-routing";
import { buildOntologyEntityDetail } from "./ontology-demo";
import {
  parseManufacturingOntology,
  parseManufacturingOntologyEntityDetail,
} from "./runtime-contracts/ontology";
import { parseManufacturingReplaySimulation } from "./runtime-contracts/simulation";
import { parseManufacturingWorkflowConsole } from "./runtime-contracts/workflows";
import {
  parsePlatformPolicyDecision,
  parsePlatformPolicyDetail,
  parsePlatformPolicyRecord,
  parsePlatformPolicyRegistry,
} from "./runtime-contracts/policies";
import {
  parseTenantQuotaSet,
  parseTenantRecord,
  parseTenantRegistry,
  parseTenantUsageSummary,
} from "./runtime-contracts/tenants";

const productionDecoders = [
  parseActionRunList,
  parseActionRunPersistenceResult,
  parseApprovalDecisionPersistenceResult,
  parseAuditExportBundle,
  parseAxisReadyReport,
  parseConnectorCsvPreviewResult,
  parseConnectorExternalDbPreviewResult,
  parseConnectorRunRecord,
  parseDemoBootstrapResult,
  parseDeploymentReadinessReport,
  parseIdentityBrowserSessionList,
  parseIdentitySessionReadModel,
  parseManufacturingActionRegistry,
  parseManufacturingAgentRegistry,
  parseManufacturingApprovalInbox,
  parseManufacturingAuditExplorer,
  parseManufacturingConnectorCredentialHandleRegistry,
  parseManufacturingConnectorCredentialLeaseRegistry,
  parseManufacturingConnectorEgressPolicyRegistry,
  parseManufacturingConnectorEvidenceInvariantReport,
  parseManufacturingConnectorEvidenceInvariantSnapshotHistory,
  parseManufacturingConnectorManifestRegistry,
  parseManufacturingConnectorOntologyProposalRegistry,
  parseManufacturingConnectorRegistry,
  parseManufacturingConnectorRunRegistry,
  parseManufacturingModelRouting,
  parseManufacturingNotificationCenter,
  parseManufacturingNotificationAcknowledgementResult,
  parseManufacturingOntology,
  parseManufacturingOntologyEntityDetail,
  parseManufacturingOperationsSnapshot,
  parseManufacturingOverview,
  parseManufacturingReplaySimulation,
  parseManufacturingWorkflowConsole,
  parseOidcReadinessReport,
  parseOperationsArtifactResponse,
  parsePlatformPolicyDecision,
  parsePlatformPolicyDetail,
  parsePlatformPolicyRecord,
  parsePlatformPolicyRegistry,
  parseSupportDiagnosticsReport,
  parseTenantQuotaSet,
  parseTenantRecord,
  parseTenantRegistry,
  parseTenantUsageSummary,
] as const;

const contractBase = {
  tenant_id: "tenant-contract",
  plant_name: null,
  scenario: null,
  provenance: "live" as const,
  as_of: "2026-07-28T00:00:00Z",
};

const actionRegistryContractFixture = {
  ...contractBase,
  registry_status: "ready",
  schema_version: "2026-07-28",
  metrics: [],
  filter_options: {
    domains: [],
    risk_levels: [],
    approval_modes: [],
    statuses: [],
  },
  actions: [],
  registry_notes: [],
};

const workflowConsoleContractFixture = {
  ...contractBase,
  runtime_status: "ready",
  metrics: [],
  workflow_runs: [],
  runtime_notes: [],
};

const replaySimulationContractFixture = {
  ...contractBase,
  simulation_status: "ready",
  metrics: [],
  retention_window: {
    policy_id: "retention-contract",
    retention_days: 30,
    legal_hold: false,
    retention_enforced: true,
    retention_window_start: "2026-06-28T00:00:00Z",
    disposal_action: "expire",
    excluded_timeline_event_count: 0,
    excluded_audit_event_count: 0,
    excluded_output_count: 0,
    notes: [],
  },
  artifacts: [],
  persisted_outputs: [],
  simulation_notes: [],
};

const evidenceSnapshotHistoryContractFixture = {
  tenant_id: contractBase.tenant_id,
  plant_name: contractBase.plant_name,
  scenario: contractBase.scenario,
  provenance: contractBase.provenance,
  history_status: "ready",
  metrics: [],
  snapshots: [],
  history_notes: [],
};

const ontologyEntityDetailFixture = buildOntologyEntityDetail(
  ontologyFixture,
  ontologyFixture.nodes[0].node_id,
);

if (!ontologyEntityDetailFixture) {
  throw new Error("The ontology contract fixture must contain its first node");
}

const provenanceContracts: ReadonlyArray<{
  name: string;
  parse: (value: unknown) => unknown;
  fixture: object;
}> = [
  {
    name: "action registry",
    parse: parseManufacturingActionRegistry,
    fixture: actionRegistryContractFixture,
  },
  {
    name: "agent registry",
    parse: parseManufacturingAgentRegistry,
    fixture: agentRegistryFixture,
  },
  {
    name: "approval inbox",
    parse: parseManufacturingApprovalInbox,
    fixture: approvalInboxFixture,
  },
  {
    name: "audit explorer",
    parse: parseManufacturingAuditExplorer,
    fixture: auditEventsFixture,
  },
  {
    name: "connector registry",
    parse: parseManufacturingConnectorRegistry,
    fixture: connectorRegistryFixture,
  },
  {
    name: "connector manifest registry",
    parse: parseManufacturingConnectorManifestRegistry,
    fixture: manifestRegistryFixture,
  },
  {
    name: "connector credential-handle registry",
    parse: parseManufacturingConnectorCredentialHandleRegistry,
    fixture: credentialHandleRegistryFixture,
  },
  {
    name: "connector credential-lease registry",
    parse: parseManufacturingConnectorCredentialLeaseRegistry,
    fixture: credentialLeaseRegistryFixture,
  },
  {
    name: "connector egress-policy registry",
    parse: parseManufacturingConnectorEgressPolicyRegistry,
    fixture: egressPolicyRegistryFixture,
  },
  {
    name: "connector run registry",
    parse: parseManufacturingConnectorRunRegistry,
    fixture: runRegistryFixture,
  },
  {
    name: "connector evidence-invariant report",
    parse: parseManufacturingConnectorEvidenceInvariantReport,
    fixture: evidenceInvariantReportFixture,
  },
  {
    name: "connector evidence-snapshot history",
    parse: parseManufacturingConnectorEvidenceInvariantSnapshotHistory,
    fixture: evidenceSnapshotHistoryContractFixture,
  },
  {
    name: "connector ontology-proposal registry",
    parse: parseManufacturingConnectorOntologyProposalRegistry,
    fixture: ontologyProposalRegistryFixture,
  },
  { name: "model routing", parse: parseManufacturingModelRouting, fixture: modelRoutingFixture },
  { name: "ontology", parse: parseManufacturingOntology, fixture: ontologyFixture },
  {
    name: "ontology entity detail",
    parse: parseManufacturingOntologyEntityDetail,
    fixture: ontologyEntityDetailFixture,
  },
  {
    name: "operations snapshot",
    parse: parseManufacturingOperationsSnapshot,
    fixture: snapshotFixture,
  },
  { name: "overview", parse: parseManufacturingOverview, fixture: overviewFixture },
  {
    name: "replay simulation",
    parse: parseManufacturingReplaySimulation,
    fixture: replaySimulationContractFixture,
  },
  {
    name: "workflow console",
    parse: parseManufacturingWorkflowConsole,
    fixture: workflowConsoleContractFixture,
  },
];

describe("production runtime contracts", () => {
  it.each(productionDecoders)("rejects an empty object at every API boundary", (parse) => {
    expect(() => parse({})).toThrow();
  });

  it("accepts a valid identity session and preserves additive compatibility", () => {
    const payload = {
      authenticated: true,
      mode: "secure_oidc_cookie",
      actor_id: "operator-1",
      tenant_id: "tenant-1",
      scopes: ["tenant:read"],
      expires_at: 1_800_000_000,
      api_auth_required: true,
      enterprise_sso_ready: true,
      readiness_status: "ready",
      issuer: "https://issuer.example",
      audience: "axis-api",
      jwks_source: "remote",
      session_boundary: "api_owned",
      capabilities: ["browser_session_rotation"],
      limitations: [],
      notes: [],
      future_additive_field: "accepted",
    };

    const parsed = parseIdentitySessionReadModel(payload);
    expect(parsed).toBe(payload);
    expect(parsed).toMatchObject({
      actor_id: "operator-1",
      authenticated: true,
      readiness_status: "ready",
    });
    expect(parsed).toHaveProperty("future_additive_field", "accepted");
  });

  it("rejects malformed nested identity fields instead of fabricating defaults", () => {
    expect(() =>
      parseIdentitySessionReadModel({
        authenticated: "yes",
        scopes: null,
      }),
    ).toThrow();
  });

  it("requires and preserves approval decision replay evidence", () => {
    const payload = {
      tenant_id: "tenant-1",
      approval_id: "approval-1",
      workflow_id: "workflow-1",
      action_id: "action-1",
      decision: "approve",
      status: "approve",
      actor_id: "operator-1",
      audit_event_id: "11111111-1111-4111-8111-111111111111",
      audit_event_type: "approval.decision.recorded",
      persisted: true,
      idempotent_replay: true,
      permission_decision: { allowed: true, reason: "allowed" },
      workflow_signal: {
        workflow_id: "workflow-1",
        status: "approval_signaled",
        adapter: "axis-test",
        signal_name: "approve",
        payload: { approval_id: "approval-1", approved: true, decision: "approve" },
      },
      workflow_signal_status: "approval_signaled",
      decision_event_id: "22222222-2222-4222-8222-222222222222",
    };

    expect(parseApprovalDecisionPersistenceResult(payload)).toMatchObject({
      idempotent_replay: true,
      decision_event_id: "22222222-2222-4222-8222-222222222222",
    });
    expect(() =>
      parseApprovalDecisionPersistenceResult({ ...payload, idempotent_replay: "yes" }),
    ).toThrow();
  });

  it("accepts action runs with waiting state and executor-reported outcomes", () => {
    const payload = {
      tenant_id: "tenant-1",
      runs: [
        {
          action_run_id: "run-waiting",
          action_id: "place_quality_hold",
          status: "approved_for_execution",
          approval_id: "approval-1",
          workflow_id: "workflow-1",
          created_at: "2026-07-24T10:00:00Z",
          updated_at: "2026-07-24T10:00:00Z",
          waiting_duration_seconds: 78_183,
          outcome: null,
        },
        {
          action_run_id: "run-reported",
          action_id: "request_supplier_expedite",
          status: "execution_completed",
          approval_id: "approval-2",
          workflow_id: "workflow-2",
          created_at: "2026-07-24T09:00:00Z",
          updated_at: "2026-07-24T11:00:00Z",
          waiting_duration_seconds: 7_200,
          outcome: {
            result_summary: "External executor completed the approved action.",
            evidence_refs: ["audit-executor-completion"],
          },
        },
      ],
    };

    expect(parseActionRunList(payload)).toBe(payload);
    expect(() =>
      parseActionRunList({
        ...payload,
        runs: [{ ...payload.runs[0], waiting_duration_seconds: -1 }],
      }),
    ).toThrow();
  });

  it("accepts scalar and collection audit references without accepting nulls", () => {
    const payload = structuredClone(snapshotFixture);
    payload.recent_audit_events[0].payload_refs = {
      scenario_id: "supplier_delay_demo",
      source_record_ids: ["order_rush_4812"],
    };

    expect(parseManufacturingOperationsSnapshot(payload)).toBe(payload);

    payload.recent_audit_events[0].payload_refs = { workflow_id: null } as never;
    expect(() => parseManufacturingOperationsSnapshot(payload)).toThrow();
  });

  it("requires and preserves notification provenance", () => {
    const payload = {
      tenant_id: "tenant-1",
      plant_name: "Plant One",
      scenario: null,
      provenance: "empty" as const,
      as_of: "2026-07-28T00:00:00Z",
      unread_count: 0,
      action_required_count: 0,
      watch_count: 0,
      notifications: [],
      generation_boundary: "derived_from_persisted_operations_snapshot",
      notes: [],
    };

    expect(parseManufacturingNotificationCenter(payload)).toBe(payload);
    const withoutProvenance = structuredClone(payload) as Partial<typeof payload>;
    delete withoutProvenance.provenance;
    expect(() => parseManufacturingNotificationCenter(withoutProvenance)).toThrow();
  });

  it("accepts nullable manufacturing context and preserves valid provenance", () => {
    const payload = {
      ...structuredClone(overviewFixture),
      plant_name: null,
      scenario: null,
      provenance: "empty" as const,
    };

    const parsed = parseManufacturingOverview(payload);

    expect(parsed).toBe(payload);
    expect(parsed.plant_name).toBeNull();
    expect(parsed.scenario).toBeNull();
    expect(parsed.provenance).toBe("empty");
    expect(parseManufacturingOverview(overviewFixture).provenance).toBe("reference_scenario");
    expect(() =>
      parseManufacturingOverview({ ...payload, provenance: "unverified" }),
    ).toThrow();
  });

  it("rejects a persisted-only connector without persistence metadata", () => {
    const payload = structuredClone(connectorRegistryFixture);
    payload.connectors[1].registry_origin = "persisted_manifest";
    payload.connectors[1].persisted_manifest = null;

    expect(() => parseManufacturingConnectorRegistry(payload)).toThrow();
  });

  it.each([
    {
      name: "nested tenant",
      mutate: (payload: typeof manifestDetailFixture) => {
        payload.current_revision.tenant_id = "tenant-cross-boundary";
      },
    },
    {
      name: "nested connector",
      mutate: (payload: typeof manifestDetailFixture) => {
        payload.revisions[0].connector_id = "connector-cross-boundary";
      },
    },
    {
      name: "nested manifest connector",
      mutate: (payload: typeof manifestDetailFixture) => {
        payload.revisions[0].manifest.connector_id = "connector-cross-boundary";
      },
    },
  ])("rejects a manifest detail with a mismatched $name", ({ mutate }) => {
    const payload = structuredClone(manifestDetailFixture);
    mutate(payload);

    expect(() => parseConnectorManifestDetail(payload)).toThrow();
  });

  it.each(provenanceContracts)(
    "rejects a $name response when provenance is missing",
    ({ parse, fixture }) => {
      expect(parse(fixture)).toBe(fixture);

      const withoutProvenance = { ...fixture } as { provenance?: unknown };
      delete withoutProvenance.provenance;

      expect(() => parse(withoutProvenance)).toThrow();
    },
  );

  it.each([
    ["overview", parseManufacturingOverview, overviewFixture],
    ["operations snapshot", parseManufacturingOperationsSnapshot, snapshotFixture],
    ["identity", parseIdentitySessionReadModel, identitySessionFixture],
    ["approval inbox", parseManufacturingApprovalInbox, approvalInboxFixture],
    ["ontology", parseManufacturingOntology, ontologyFixture],
    ["model routing", parseManufacturingModelRouting, modelRoutingFixture],
    ["audit explorer", parseManufacturingAuditExplorer, auditEventsFixture],
    ["policy registry", parsePlatformPolicyRegistry, policyRegistryFixture],
    ["connector registry", parseManufacturingConnectorRegistry, connectorRegistryFixture],
    ["connector manifests", parseManufacturingConnectorManifestRegistry, manifestRegistryFixture],
    [
      "connector credential handles",
      parseManufacturingConnectorCredentialHandleRegistry,
      credentialHandleRegistryFixture,
    ],
    [
      "connector credential leases",
      parseManufacturingConnectorCredentialLeaseRegistry,
      credentialLeaseRegistryFixture,
    ],
    ["connector egress policies", parseManufacturingConnectorEgressPolicyRegistry, egressPolicyRegistryFixture],
    ["connector runs", parseManufacturingConnectorRunRegistry, runRegistryFixture],
    [
      "connector evidence invariants",
      parseManufacturingConnectorEvidenceInvariantReport,
      evidenceInvariantReportFixture,
    ],
    [
      "connector ontology proposals",
      parseManufacturingConnectorOntologyProposalRegistry,
      ontologyProposalRegistryFixture,
    ],
  ] as const)("accepts the representative %s payload", (_name, parse, fixture) => {
    expect(parse(fixture)).toBe(fixture);
  });
});
