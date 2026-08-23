import { describe, expect, it } from "vitest";

import type {
  ConnectorCredentialLeaseRecord,
  ConnectorManifestDetail,
  ConnectorOntologyProposalRecord,
  ConnectorPreviewSample,
  ConnectorRegistryItem,
} from "./connectors-demo";
import {
  allLiveRequirementsMet,
  buildCsvFromPreviewSample,
  buildExternalDbPreviewRequest,
  buildManifestCreateRequest,
  buildManifestLifecycleRequest,
  buildPreviewSyncPlan,
  connectorWithCurrentManifest,
  deriveConnectorId,
  findActiveLeaseForConnector,
  liveEnablementRequirements,
  manifestAllowsRuns,
  manifestLifecycleTargets,
  missingLiveEvidenceCategories,
  parseCsvText,
  pendingProposalCount,
  buildSourceDiscoveryRequest,
  buildSourceIngestionReadPath,
  buildSourceIngestionRedispatchRequest,
  buildSourceIngestionRequest,
  buildSourceVerifyRequest,
  SOURCE_INGESTION_ENDPOINTS,
  SOURCE_INGESTION_SCOPE,
} from "./connectors-console";

const previewSample: ConnectorPreviewSample = {
  file_name: "assets.csv",
  record_count: 2,
  headers: ["asset_id", "asset_name"],
  sample_rows: [
    { asset_id: "ast-1", asset_name: "CNC Mill, hall \"A\"" },
    { asset_id: "ast-2", asset_name: "Press" },
  ],
};

const templateConnector: ConnectorRegistryItem = {
  manifest: {
    connector_id: "file_csv_manufacturing_assets",
    display_name: "Manufacturing assets CSV",
    connector_type: "file_csv",
    version: "1.0.0",
    source_type: "csv_upload",
    sync_modes: ["preview"],
    runtime_boundary: "self_hosted",
    required_permissions: ["connectors:preview"],
    credential_requirements: {
      storage: "none",
      required_secret_refs: [],
      notes: [],
    },
    schema_fields: [
      {
        source_column: "asset_id",
        target_field: "node_id",
        ontology_target: "manufacturing_asset",
        data_type: "string",
        required: true,
        description: "Asset identifier",
      },
    ],
    mapping_notes: [],
  },
  runtime_policy: {
    allowed_operations: ["preview"],
    blocked_operations: ["live_query"],
    egress_policy: "no-external-egress",
    max_file_size_mb: 5,
    row_limit: 100,
    payload_policy: "metadata_only",
  },
  preview_sample: previewSample,
  last_successful_sync: null,
  connector_status: "watch",
  registry_origin: "reference",
  persisted_manifest: null,
};

function buildManifestDetail(
  connector: ConnectorRegistryItem,
  input: {
    manifestId: string;
    revisionNumber: number;
    connectorId?: string;
    embeddedConnectorId?: string;
    displayName?: string;
  },
): ConnectorManifestDetail {
  const connectorId = input.connectorId ?? connector.manifest.connector_id;
  const manifest = {
    ...connector.manifest,
    connector_id: input.embeddedConnectorId ?? connectorId,
    display_name: input.displayName ?? connector.manifest.display_name,
  };
  const currentRevision: ConnectorManifestDetail["current_revision"] = {
    tenant_id: "tenant_demo_manufacturing",
    manifest_id: input.manifestId,
    connector_id: connectorId,
    revision_number: input.revisionNumber,
    display_name: manifest.display_name,
    connector_type: manifest.connector_type,
    source_type: manifest.source_type,
    version: manifest.version,
    status: "active_preview",
    runtime_boundary: manifest.runtime_boundary,
    registered_by: "manifest-detail-reader",
    manifest,
    runtime_policy: connector.runtime_policy,
    preview_sample: connector.preview_sample,
    audit_event_id: `audit-${input.manifestId}`,
    audit_event_type: "connector.manifest.registered",
    revises_revision_number:
      input.revisionNumber > 1 ? input.revisionNumber - 1 : null,
    replaced_by_revision_number: null,
    revision_idempotency_key: `revision-${input.manifestId}`,
    idempotent_replay: false,
    unchanged: false,
    notes: [`detail ${input.manifestId}`],
    created_at: "2026-07-10T08:00:00Z",
  };

  return {
    tenant_id: currentRevision.tenant_id,
    connector_id: currentRevision.connector_id,
    current_revision: currentRevision,
    revisions: [currentRevision],
    transitions: [],
  };
}

function leaseRecord(
  overrides: Partial<ConnectorCredentialLeaseRecord>,
): ConnectorCredentialLeaseRecord {
  return {
    tenant_id: "tenant_demo_manufacturing",
    connector_id: "file_csv_manufacturing_assets",
    handle_id: "handle_a",
    lease_id: "lease_a",
    status: "active",
    lease_mode: "read_only",
    runtime_boundary: "self_hosted",
    requested_by: "worker",
    lease_purpose: "sync",
    secret_provider: "vault",
    secret_ref: "vault://x",
    vault_kms_policy: {},
    permission_decision: { allowed: true, reason: "scope_present" },
    lease_result: {},
    granted_at: "2026-07-10T00:00:00Z",
    expires_at: "2999-01-01T00:00:00Z",
    renewal_due_at: "2999-01-01T00:00:00Z",
    renewed_at: null,
    renewed_by: null,
    renewal_count: 0,
    revoked_at: null,
    revoked_by: null,
    revocation_reason: null,
    audit_event_id: null,
    audit_event_type: "connector.credential.lease",
    notes: [],
    created_at: "2026-07-10T00:00:00Z",
    ...overrides,
  };
}

describe("parseCsvText", () => {
  it("parses headers and rows", () => {
    const parsed = parseCsvText("asset_id,asset_name\nast-1,CNC Mill\nast-2,Press\n");

    expect(parsed.headers).toEqual(["asset_id", "asset_name"]);
    expect(parsed.rows).toEqual([
      { asset_id: "ast-1", asset_name: "CNC Mill" },
      { asset_id: "ast-2", asset_name: "Press" },
    ]);
  });

  it("handles quoted fields containing commas, quotes and newlines", () => {
    const parsed = parseCsvText(
      'asset_id,asset_name\nast-1,"Mill, hall ""A"""\nast-2,"Two\nlines"',
    );

    expect(parsed.rows[0].asset_name).toBe('Mill, hall "A"');
    expect(parsed.rows[1].asset_name).toBe("Two\nlines");
  });

  it("returns empty rows for a header-only file", () => {
    const parsed = parseCsvText("asset_id,asset_name");

    expect(parsed.headers).toEqual(["asset_id", "asset_name"]);
    expect(parsed.rows).toEqual([]);
  });
});

describe("buildCsvFromPreviewSample", () => {
  it("round-trips the recorded sample through the CSV format", () => {
    const csv = buildCsvFromPreviewSample(previewSample);
    const parsed = parseCsvText(csv);

    expect(parsed.headers).toEqual(previewSample.headers);
    expect(parsed.rows).toEqual(previewSample.sample_rows);
  });
});

describe("deriveConnectorId", () => {
  it("builds a safe snake_case id from a file name", () => {
    expect(deriveConnectorId("Plant Assets (Q3).csv", "file_csv")).toBe(
      "file_csv_plant_assets_q3",
    );
  });

  it("falls back to a generic id for unusable names", () => {
    expect(deriveConnectorId("###.csv", "external_db")).toBe("external_db_connector");
  });
});

describe("buildManifestCreateRequest", () => {
  it("copies the template and overrides identity, preview sample and notes", () => {
    const request = buildManifestCreateRequest({
      tenantId: "tenant_demo_manufacturing",
      registeredBy: "plant-operations-owner-role",
      template: templateConnector,
      connectorId: "file_csv_new_assets",
      displayName: "New assets",
      previewSample: previewSample,
    });

    expect(request.tenant_id).toBe("tenant_demo_manufacturing");
    expect(request.registered_by).toBe("plant-operations-owner-role");
    expect(request.manifest.connector_id).toBe("file_csv_new_assets");
    expect(request.manifest.display_name).toBe("New assets");
    expect(request.manifest.connector_type).toBe("file_csv");
    expect(request.manifest.schema_fields).toEqual(templateConnector.manifest.schema_fields);
    expect(request.runtime_policy).toEqual(templateConnector.runtime_policy);
    expect(request.preview_sample).toEqual(previewSample);
    // The template object must not be mutated.
    expect(templateConnector.manifest.connector_id).toBe("file_csv_manufacturing_assets");
  });
});

describe("buildExternalDbPreviewRequest", () => {
  it("selects the template's schema columns and keeps metadata public-safe", () => {
    const request = buildExternalDbPreviewRequest({
      tenantId: "tenant_demo_manufacturing",
      connectorId: "external_db_operational_mirror",
      connectionProfileId: "profile_postgres_ops_readonly",
      schemaName: "operations",
      tableName: "production_orders",
      credentialHandleId: "cred_external_db_readonly",
      template: templateConnector,
    });

    expect(request.selected_columns).toEqual(["asset_id"]);
    expect(request.metadata).toEqual({});
    expect(request.sample_limit).toBeGreaterThan(0);
  });
});

describe("findActiveLeaseForConnector", () => {
  const now = new Date("2026-07-11T00:00:00Z");

  it("returns the first active unexpired lease for the connector", () => {
    const leases = [
      leaseRecord({ lease_id: "lease_other", connector_id: "other" }),
      leaseRecord({ lease_id: "lease_expired", expires_at: "2020-01-01T00:00:00Z" }),
      leaseRecord({ lease_id: "lease_revoked", status: "revoked" }),
      leaseRecord({ lease_id: "lease_good" }),
    ];

    expect(
      findActiveLeaseForConnector(leases, "file_csv_manufacturing_assets", now)?.lease_id,
    ).toBe("lease_good");
  });

  it("returns null when nothing matches", () => {
    expect(findActiveLeaseForConnector([], "file_csv_manufacturing_assets", now)).toBeNull();
  });
});

describe("buildPreviewSyncPlan", () => {
  it("derives run, dispatch and execute payloads with idempotency keys from one token", () => {
    const plan = buildPreviewSyncPlan({
      tenantId: "tenant_demo_manufacturing",
      connectorId: "file_csv_manufacturing_assets",
      actorId: "plant-operations-owner-role",
      lease: leaseRecord({}),
      now: new Date("2026-07-11T08:00:00Z"),
      token: "abc123",
    });

    expect(plan.runId).toBe("run_console_abc123");
    expect(plan.runId).toMatch(/^[a-z0-9][a-z0-9_-]*$/);
    expect(plan.create).toEqual({
      tenant_id: "tenant_demo_manufacturing",
      connector_id: "file_csv_manufacturing_assets",
      run_id: "run_console_abc123",
      execution_mode: "scheduled_sync_plan",
      requested_by: "plant-operations-owner-role",
      credential_handle_ids: ["handle_a"],
      credential_lease_id: "lease_a",
      schedule_id: "sched_console_abc123",
      schedule_cadence: "manual_preview",
      schedule_timezone: "UTC",
      next_run_at: "2026-07-11T08:00:00.000Z",
      input_summary: { trigger: "connector-console-preview-sync" },
      result_summary: {},
      notes: ["Preview sync started from the connector console."],
    });
    expect(plan.dispatch.dispatch_id).toBe("dispatch_console_abc123");
    expect(plan.dispatch.actor_scopes).toEqual(["connectors:sync:dispatch"]);
    expect(plan.dispatch.credential_lease_id).toBe("lease_a");
    expect(plan.dispatch.idempotency_key).toBe("idem_dispatch_console_abc123");
    expect(plan.execute.execution_id).toBe("exec_console_abc123");
    expect(plan.execute.actor_scopes).toEqual(["connectors:sync:execute"]);
    expect(plan.execute.idempotency_key).toBe("idem_exec_console_abc123");
  });
});

describe("registry summaries", () => {
  it("counts proposals that have not been promoted yet", () => {
    const proposals = [
      { promoted_at: null },
      { promoted_at: "2026-07-10T00:00:00Z" },
      { promoted_at: null },
    ] as ConnectorOntologyProposalRecord[];

    expect(pendingProposalCount(proposals)).toBe(2);
  });

  it("allows runs only for an explicitly active persisted manifest", () => {
    expect(manifestAllowsRuns({ status: "active_preview" })).toBe(true);
    expect(manifestAllowsRuns({ status: "active_live" })).toBe(true);
    expect(manifestAllowsRuns({ status: "registered_preview_only" })).toBe(false);
    expect(manifestAllowsRuns(null)).toBe(false);
  });
});

describe("connectorWithCurrentManifest", () => {
  it("uses the fetched current revision while preserving registry provenance and sync evidence", () => {
    const connector: ConnectorRegistryItem = {
      ...templateConnector,
      registry_origin: "persisted_manifest",
      persisted_manifest: {
        manifest_id: "manifest-stale",
        revision_number: 1,
        status: "registered_preview_only",
        registered_by: "registry-reader",
        registered_at: "2026-07-09T08:00:00Z",
        notes: ["stale registry summary"],
      },
      last_successful_sync: {
        run_id: "run-previous",
        completed_at: "2026-07-09T09:00:00Z",
        records_read: 7,
      },
    };
    const currentManifest = {
      ...connector.manifest,
      display_name: "Current manufacturing assets",
      version: "2.0.0",
      schema_fields: [
        {
          ...connector.manifest.schema_fields[0],
          source_column: "current_asset_id",
        },
      ],
    };
    const currentRevision = {
      tenant_id: "tenant_demo_manufacturing",
      manifest_id: "manifest-current",
      connector_id: currentManifest.connector_id,
      revision_number: 2,
      display_name: currentManifest.display_name,
      connector_type: currentManifest.connector_type,
      source_type: currentManifest.source_type,
      version: currentManifest.version,
      status: "active_live",
      runtime_boundary: currentManifest.runtime_boundary,
      registered_by: "manifest-detail-reader",
      manifest: currentManifest,
      runtime_policy: {
        ...connector.runtime_policy,
        row_limit: 250,
      },
      preview_sample: connector.preview_sample,
      audit_event_id: "audit-manifest-current",
      audit_event_type: "connector.manifest.registered",
      revises_revision_number: 1,
      replaced_by_revision_number: null,
      revision_idempotency_key: "revision-current",
      idempotent_replay: false,
      unchanged: false,
      notes: ["authoritative current revision"],
      created_at: "2026-07-10T08:00:00Z",
    };
    const detail: ConnectorManifestDetail = {
      tenant_id: currentRevision.tenant_id,
      connector_id: currentRevision.connector_id,
      current_revision: currentRevision,
      revisions: [currentRevision],
      transitions: [],
    };

    const effective = connectorWithCurrentManifest(connector, detail);

    expect(effective.manifest).toBe(currentRevision.manifest);
    expect(effective.runtime_policy).toBe(currentRevision.runtime_policy);
    expect(effective.preview_sample).toBe(currentRevision.preview_sample);
    expect(effective.persisted_manifest).toEqual({
      manifest_id: "manifest-current",
      revision_number: 2,
      status: "active_live",
      registered_by: "manifest-detail-reader",
      registered_at: "2026-07-10T08:00:00Z",
      notes: ["authoritative current revision"],
    });
    expect(effective.registry_origin).toBe("persisted_manifest");
    expect(effective.connector_status).toBe(connector.connector_status);
    expect(effective.last_successful_sync).toBe(connector.last_successful_sync);
    expect(connector.persisted_manifest?.status).toBe("registered_preview_only");
  });

  it("returns the registry connector unchanged while detail is unavailable", () => {
    expect(connectorWithCurrentManifest(templateConnector, null)).toBe(templateConnector);
  });

  it("does not let retained detail roll a newer registry revision backward", () => {
    const connector: ConnectorRegistryItem = {
      ...templateConnector,
      manifest: {
        ...templateConnector.manifest,
        display_name: "Registry revision three",
        version: "3.0.0",
      },
      registry_origin: "persisted_manifest",
      persisted_manifest: {
        manifest_id: "manifest-current",
        revision_number: 3,
        status: "active_live",
        registered_by: "registry-reader",
        registered_at: "2026-07-11T08:00:00Z",
        notes: ["fresh registry summary"],
      },
    };
    const retainedDetail = buildManifestDetail(connector, {
      manifestId: "manifest-stale",
      revisionNumber: 2,
      displayName: "Retained revision two",
    });

    expect(connectorWithCurrentManifest(connector, retainedDetail)).toBe(connector);
  });

  it("uses equal-revision detail only when the manifest identity agrees", () => {
    const connector: ConnectorRegistryItem = {
      ...templateConnector,
      registry_origin: "persisted_manifest",
      persisted_manifest: {
        manifest_id: "manifest-current",
        revision_number: 2,
        status: "active_preview",
        registered_by: "registry-reader",
        registered_at: "2026-07-10T07:00:00Z",
        notes: ["registry summary"],
      },
    };
    const matchingDetail = buildManifestDetail(connector, {
      manifestId: "manifest-current",
      revisionNumber: 2,
      displayName: "Authoritative matching detail",
    });
    const divergentDetail = buildManifestDetail(connector, {
      manifestId: "manifest-divergent",
      revisionNumber: 2,
      displayName: "Divergent equal revision",
    });

    expect(connectorWithCurrentManifest(connector, matchingDetail).manifest.display_name).toBe(
      "Authoritative matching detail",
    );
    expect(connectorWithCurrentManifest(connector, divergentDetail)).toBe(connector);
  });

  it("ignores retained detail for a different or no-longer-persisted connector", () => {
    const persistedConnector: ConnectorRegistryItem = {
      ...templateConnector,
      registry_origin: "persisted_manifest",
      persisted_manifest: {
        manifest_id: "manifest-current",
        revision_number: 2,
        status: "active_preview",
        registered_by: "registry-reader",
        registered_at: "2026-07-10T07:00:00Z",
        notes: [],
      },
    };
    const otherConnectorDetail = buildManifestDetail(persistedConnector, {
      manifestId: "manifest-other",
      revisionNumber: 3,
      connectorId: "file_csv_other_connector",
    });
    const retainedMatchingDetail = buildManifestDetail(templateConnector, {
      manifestId: "manifest-removed",
      revisionNumber: 3,
    });

    expect(connectorWithCurrentManifest(persistedConnector, otherConnectorDetail)).toBe(
      persistedConnector,
    );
    expect(connectorWithCurrentManifest(templateConnector, retainedMatchingDetail)).toBe(
      templateConnector,
    );
  });
});

describe("connector manifest lifecycle", () => {
  it("mirrors the API transition table per current status", () => {
    expect(manifestLifecycleTargets("registered_preview_only")).toEqual([
      "active_preview",
      "deprecated",
    ]);
    expect(manifestLifecycleTargets("active_preview")).toEqual(["active_live", "deprecated"]);
    expect(manifestLifecycleTargets("active_live")).toEqual(["deprecated"]);
    expect(manifestLifecycleTargets("deprecated")).toEqual([]);
    expect(manifestLifecycleTargets(null)).toEqual([]);
  });

  it("builds lifecycle requests with the scope the API requires for live enablement", () => {
    const activate = buildManifestLifecycleRequest({
      tenantId: "tenant_demo_manufacturing",
      actorId: "operator",
      targetStatus: "active_preview",
      reason: "Activated from the connector console.",
    });
    expect(activate).toMatchObject({
      tenant_id: "tenant_demo_manufacturing",
      transitioned_by: "operator",
      target_status: "active_preview",
      required_scope: "connectors:manifest:lifecycle",
      // Demo-mode writes declare the grant they run under; the API still
      // enforces it and re-stamps scopes from the token for SSO sessions.
      actor_scopes: ["connectors:manifest:lifecycle"],
      evidence_refs: [],
    });

    const enableLive = buildManifestLifecycleRequest({
      tenantId: "tenant_demo_manufacturing",
      actorId: "operator",
      targetStatus: "active_live",
      reason: "Enable live sync…",
      evidenceRefs: ["approval:ap-1", "policy:pol-1", "credential:cred-1"],
    });
    // The API checks both scopes for live enablement
    // (_required_scopes_for_target), so a demo-mode submission declares both.
    expect(enableLive.required_scope).toBe("connectors:manifest:lifecycle");
    expect(enableLive.actor_scopes).toEqual([
      "connectors:manifest:lifecycle",
      "connectors:manifest:enable_live",
    ]);
    expect(enableLive.evidence_refs).toHaveLength(3);
  });

  it("reports exactly which evidence categories are missing for live enablement", () => {
    expect(missingLiveEvidenceCategories([])).toEqual(["approval", "policy", "credential"]);
    expect(
      missingLiveEvidenceCategories(["approval:ap-1"]),
    ).toEqual(["policy", "credential"]);
    // The API accepts secret:/vault: handles as credential evidence too.
    expect(
      missingLiveEvidenceCategories([
        "approval: ap-1",
        "policy:pol-1",
        "vault://prod/db-readonly",
      ]),
    ).toEqual([]);
  });

  it("reports which live-enablement gates the manifest already satisfies", () => {
    const dormant = liveEnablementRequirements(templateConnector);
    expect(dormant.liveSyncMode.met).toBe(false);
    expect(dormant.liveOperationsAllowed.met).toBe(false);
    expect(dormant.egressBoundaryNamed.met).toBe(false);

    const liveReady = liveEnablementRequirements({
      ...templateConnector,
      manifest: {
        ...templateConnector.manifest,
        sync_modes: ["live_sync"],
      },
      runtime_policy: {
        ...templateConnector.runtime_policy,
        allowed_operations: ["preview", "live_query", "external_egress"],
        blocked_operations: [],
        egress_policy: "egress_eu_west_readonly",
      },
    });
    expect(allLiveRequirementsMet(liveReady)).toBe(true);
  });
});

describe("buildSourceVerifyRequest / buildSourceDiscoveryRequest", () => {
  const baseInput = {
    tenantId: "tenant_demo_manufacturing",
    actorId: "axis-operator",
    refs: {
      connectionProfileId: "profile_postgres_discovery_readonly",
      schemaName: "operations",
      credentialLeaseId: "lease_external_db_readonly_001",
      egressPolicyId: "egress_policy_private_endpoint_ops",
    },
    token: "ABC-123",
  };

  it("names references only and declares the discovery scope", () => {
    const payload = buildSourceVerifyRequest(baseInput);
    expect(payload).toMatchObject({
      tenant_id: "tenant_demo_manufacturing",
      connector_id: "external_db_operational_mirror",
      verification_id: "verify_console_abc123",
      requested_by: "axis-operator",
      connection_profile_id: "profile_postgres_discovery_readonly",
      credential_lease_id: "lease_external_db_readonly_001",
      egress_policy_id: "egress_policy_private_endpoint_ops",
      actor_scopes: ["connectors:source:discover"],
    });
    // Evidence is resolved server-side; the request must not carry it.
    expect(payload).not.toHaveProperty("credential_lease_result");
    expect(payload).not.toHaveProperty("egress_policy_evidence");
  });

  it("includes the requested schema for discovery with a stable id", () => {
    const payload = buildSourceDiscoveryRequest(baseInput);
    expect(payload.discovery_id).toBe("discovery_console_abc123");
    expect(payload.schema_name).toBe("operations");
    expect(payload.actor_scopes).toEqual(["connectors:source:discover"]);
  });

  it("refuses to build a discovery request without a schema", () => {
    expect(() =>
      buildSourceDiscoveryRequest({
        ...baseInput,
        refs: { ...baseInput.refs, schemaName: "" },
      }),
    ).toThrow(/Schema name is required/);
  });
});

describe("buildSourceIngestionRequest", () => {
  const baseInput = {
    tenantId: "tenant_demo_manufacturing",
    actorId: "axis-operator",
    requestId: "ingest_console_abc123",
    reason: "Nightly governed validation before extraction design review.",
    bindingIds: ["binding_console_a", "binding_console_b"],
  };

  it("names bindings only and declares the ingestion scope", () => {
    const payload = buildSourceIngestionRequest(baseInput);
    expect(payload).toMatchObject({
      tenant_id: "tenant_demo_manufacturing",
      connector_id: "external_db_operational_mirror",
      request_id: "ingest_console_abc123",
      requested_by: "axis-operator",
      selections: [
        { binding_id: "binding_console_a" },
        { binding_id: "binding_console_b" },
      ],
      actor_scopes: [SOURCE_INGESTION_SCOPE],
    });
    // Fingerprints are pinned server-side from the active bindings; the
    // client never supplies one and the payload must prove it.
    expect(JSON.stringify(payload)).not.toContain("fingerprint");
  });

  it("deduplicates repeated binding ids instead of double-submitting them", () => {
    const payload = buildSourceIngestionRequest({
      ...baseInput,
      bindingIds: ["binding_console_a", "binding_console_a"],
    });
    expect(payload.selections).toEqual([{ binding_id: "binding_console_a" }]);
  });

  it("refuses to build without a reason, request id, or any binding", () => {
    expect(() => buildSourceIngestionRequest({ ...baseInput, reason: "   " }))
      .toThrow(/governance reason is required/i);
    expect(() => buildSourceIngestionRequest({ ...baseInput, requestId: " " }))
      .toThrow(/request ID is required/i);
    expect(() => buildSourceIngestionRequest({ ...baseInput, bindingIds: [] }))
      .toThrow(/At least one pending binding/);
  });

  it("builds read paths with tenant, connector, and the demo read scope", () => {
    expect(buildSourceIngestionReadPath({
      endpoint: SOURCE_INGESTION_ENDPOINTS.eligibility,
      tenantId: "tenant_demo_manufacturing",
      connectorId: "external_db_operational_mirror",
    })).toBe(
      `${SOURCE_INGESTION_ENDPOINTS.eligibility}`
      + "?tenant_id=tenant_demo_manufacturing"
      + "&connector_id=external_db_operational_mirror"
      + "&actor_scopes=connectors%3Asource%3Aingest%3Aread",
    );
    expect(buildSourceIngestionReadPath({
      endpoint: SOURCE_INGESTION_ENDPOINTS.requests,
      tenantId: "tenant_demo_manufacturing",
      requestId: "ingest_console_abc123",
    })).toBe(
      `${SOURCE_INGESTION_ENDPOINTS.requests}/ingest_console_abc123`
      + "?tenant_id=tenant_demo_manufacturing"
      + "&actor_scopes=connectors%3Asource%3Aingest%3Aread",
    );
  });
});

describe("buildSourceIngestionRedispatchRequest", () => {
  it("requires the remediation reason and carries the explicit idempotency key", () => {
    expect(() =>
      buildSourceIngestionRedispatchRequest({
        tenantId: "t",
        actorId: "a",
        reason: "   ",
        idempotencyKey: "requeue_1",
      }),
    ).toThrow(/remediation reason is required/i);
    expect(() =>
      buildSourceIngestionRedispatchRequest({
        tenantId: "t",
        actorId: "a",
        reason: "ok",
        idempotencyKey: " ",
      }),
    ).toThrow(/idempotency key is required/i);
    const payload = buildSourceIngestionRedispatchRequest({
      tenantId: "t",
      actorId: "a",
      reason: "Fresh discovery done.",
      idempotencyKey: "requeue_lane_001",
    });
    expect(payload).toMatchObject({
      tenant_id: "t",
      requeued_by: "a",
      reason: "Fresh discovery done.",
      idempotency_key: "requeue_lane_001",
      actor_scopes: ["connectors:source:ingest"],
    });
  });
});
