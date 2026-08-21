import { describe, expect, it } from "vitest";

import {
  allActionFilter,
  actionRunWorkflowSignalLabel,
  buildActionRunIdempotencyKey,
  buildActionRunRequest,
  buildTypedActionPayload,
  countApprovalGatedActions,
  filterActions,
  findActionById,
  formatActionLabel,
  formatSchemaFields,
  type ManufacturingActionRegistry,
} from "./action-demo";

const actionRegistryFixture: ManufacturingActionRegistry = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-06-22T09:00:00+02:00",
  registry_status: "ready",
  schema_version: "2026-06-22",
  metrics: [],
  filter_options: {
    domains: ["Supply", "Operations"],
    risk_levels: ["high", "low"],
    approval_modes: ["required", "not_required"],
    statuses: ["approval_required", "ready"],
  },
  actions: [
    {
      definition: {
        action_id: "expedite_fixture_batch",
        display_name: "Expedite fixture batch",
        domain: "Supply",
        risk_level: "high",
        approval_mode: "required",
        input_schema: {
          type: "object",
          required: ["supplier_batch_id", "evidence_refs"],
          properties: {
            supplier_batch_id: { type: "string", "x-axis-ontology-ref": true },
            evidence_refs: { type: "array", items: { type: "string" } },
          },
        },
        output_schema: { type: "object", properties: { status: { type: "string" } } },
        required_permissions: ["approvals:supply:request"],
      },
      description: "Fixture action requiring owner approval.",
      owner_role: "supply-owner",
      status: "approval_required",
      side_effects: "Requests an external shipment update through the action runtime.",
      policy: {
        approval_role: "supply-owner",
        autonomy_ceiling: "L2",
        execution_mode: "dry_run",
        runtime_adapter: "axis-action-runtime",
        audit_event_type: "action.requested",
        model_egress_policy: "no-external-egress",
        idempotency_required: true,
        dry_run_supported: true,
      },
      connected_agents: ["agent_supply_fixture"],
      workflow_bindings: ["wf_supply_fixture"],
      approval_refs: ["appr_supply_fixture"],
      guardrails: ["Require human approval"],
      validation_checks: ["Validate supplier batch"],
      blocked_conditions: ["Missing owner approval"],
      sample_input: {
        supplier_batch_id: "batch-42",
        evidence_refs: "risk_supply_fixture,audit_fixture",
      },
      sample_output: { status: "queued" },
    },
    {
      definition: {
        action_id: "brief_fixture",
        display_name: "Generate fixture brief",
        domain: "Operations",
        risk_level: "low",
        approval_mode: "not_required",
        input_schema: { type: "object", properties: { shift: { type: "string" } } },
        output_schema: { type: "object", properties: { summary: { type: "string" } } },
        required_permissions: ["operations:read"],
      },
      description: "Read-only operational summary.",
      owner_role: "operations-owner",
      status: "ready",
      side_effects: "None.",
      policy: {
        approval_role: "operations-owner",
        autonomy_ceiling: "L1",
        execution_mode: "preview",
        runtime_adapter: "axis-action-runtime",
        audit_event_type: "action.previewed",
        model_egress_policy: "local-only",
        idempotency_required: true,
        dry_run_supported: true,
      },
      connected_agents: [],
      workflow_bindings: [],
      approval_refs: [],
      guardrails: ["Read-only output"],
      validation_checks: ["Validate shift"],
      blocked_conditions: ["No tenant context"],
      sample_input: { shift: "morning" },
      sample_output: { summary: "ready" },
    },
  ],
  registry_notes: ["Fixture data is scoped to tests."],
};

describe("action registry helpers", () => {
  it("filters actions by domain, risk, approval mode and status", () => {
    const actions = filterActions(actionRegistryFixture, {
      domain: "Supply",
      riskLevel: "high",
      approvalMode: "required",
      status: "approval_required",
    });

    expect(actions).toHaveLength(1);
    expect(actions[0].definition.action_id).toBe("expedite_fixture_batch");
  });

  it("keeps all actions when filters are set to all", () => {
    expect(
      filterActions(actionRegistryFixture, {
        domain: allActionFilter,
        riskLevel: allActionFilter,
        approvalMode: allActionFilter,
        status: allActionFilter,
      }),
    ).toHaveLength(actionRegistryFixture.actions.length);
  });

  it("finds actions by id with a safe fallback", () => {
    expect(findActionById(actionRegistryFixture, "expedite_fixture_batch").definition.display_name)
      .toBe("Expedite fixture batch");
    expect(findActionById(actionRegistryFixture, "missing").definition.display_name).toBe(
      "Expedite fixture batch",
    );
  });

  it("counts gated actions and formats labels", () => {
    expect(countApprovalGatedActions(actionRegistryFixture)).toBe(1);
    expect(formatActionLabel("approval_gated_dry_run")).toBe("Approval Gated Dry Run");
    expect(formatActionLabel("approvals:supply:request")).toBe("Approvals Supply Request");
  });

  it("formats schema fields with required markers", () => {
    const supplyAction = findActionById(actionRegistryFixture, "expedite_fixture_batch");

    expect(formatSchemaFields(supplyAction.definition.input_schema)).toEqual([
      "supplier_batch_id: string (required)",
      "evidence_refs: string[] (required)",
    ]);
  });

  it("builds typed action run requests from provided action data", () => {
    const supplyAction = findActionById(actionRegistryFixture, "expedite_fixture_batch");
    const payload = buildTypedActionPayload(supplyAction);
    const request = buildActionRunRequest(actionRegistryFixture, supplyAction);

    expect(payload.evidence_refs).toEqual(["risk_supply_fixture", "audit_fixture"]);
    expect(request).toMatchObject({
      actor_id: "agent_supply_fixture",
      actor_scopes: ["approvals:supply:request"],
      idempotency_key: "tenant_fixture:expedite_fixture_batch:appr_supply_fixture",
    });
  });

  it("uses the verified actor and registry tenant for authenticated action runs", () => {
    const supplyAction = findActionById(actionRegistryFixture, "expedite_fixture_batch");
    const tenantAwareAction = {
      ...supplyAction,
      definition: {
        ...supplyAction.definition,
        input_schema: {
          ...supplyAction.definition.input_schema,
          properties: {
            ...supplyAction.definition.input_schema.properties,
            tenant_id: { type: "string" },
          },
        },
      },
      sample_input: {
        ...supplyAction.sample_input,
        tenant_id: "tenant_demo_manufacturing",
      },
    };

    expect(
      buildActionRunRequest(actionRegistryFixture, tenantAwareAction, {
        actorId: "acme-operator",
        scopes: ["approvals:supply:request", "tenant:read"],
      }),
    ).toMatchObject({
      actor_id: "acme-operator",
      actor_scopes: ["approvals:supply:request", "tenant:read"],
      payload: { tenant_id: "tenant_fixture" },
    });
  });

  it("keeps action run idempotency keys stable for approval-gated actions", () => {
    const supplyAction = findActionById(actionRegistryFixture, "expedite_fixture_batch");

    expect(buildActionRunIdempotencyKey(actionRegistryFixture, supplyAction)).toBe(
      "tenant_fixture:expedite_fixture_batch:appr_supply_fixture",
    );
  });

  it("formats action run workflow signal status for persisted results", () => {
    expect(
      actionRunWorkflowSignalLabel({
        workflow_signal_status: "action_signal_requested",
        workflow_signal: {
          adapter: "axis-temporal-adapter",
          signal_name: "action_requested",
        },
      }),
    ).toBe("action_signal_requested via axis-temporal-adapter / action_requested");

    expect(actionRunWorkflowSignalLabel({ workflow_signal_status: "not_required" })).toBe(
      "workflow signal not required",
    );
  });
});
