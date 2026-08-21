import type {
  IdentitySessionReadModel,
  ManufacturingOperationsSnapshot,
} from "./platform-overview";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

export type OperationsArtifactKind =
  | "daily_brief"
  | "quality_risk"
  | "maintenance_risk"
  | "supplier_delay";

export type OperationsArtifactAction = {
  kind: OperationsArtifactKind;
  label: string;
  description: string;
  endpoint: string;
  requiredScopes: string[];
};

export type OperationsArtifactRequestBody = {
  tenant_id: string;
  requested_by: string;
  actor_scopes: string[];
  idempotency_key: string;
  limit: number;
  brief_date?: string;
};

export type OperationsArtifactRequest = {
  action: OperationsArtifactAction;
  endpoint: string;
  body: OperationsArtifactRequestBody;
};

export type OperationsArtifactResponse = {
  tenant_id: string;
  status: string;
  requested_by: string;
  audit_event_id: string | null;
  audit_event_type: string;
  idempotent_replay: boolean;
  source_record_ids: string[];
  brief_id?: string;
  brief_date?: string;
  summary_payload?: { headline?: string };
  scenario_id?: string;
  domain?: string;
  risk_level?: string;
  owner_role?: string;
  workflow_ids?: string[];
  scenario_payload?: { headline?: string };
};

export type OperationsArtifactActionState = {
  action: OperationsArtifactAction;
  canRun: boolean;
  missingScopes: string[];
  reason: string | null;
};

type BuildOperationsArtifactRequestInput = {
  kind: OperationsArtifactKind;
  identitySession: IdentitySessionReadModel | null;
  snapshot: ManufacturingOperationsSnapshot;
};

export class OperationsArtifactRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OperationsArtifactRequestError";
  }
}

export const OPERATIONS_ARTIFACT_ACTIONS: OperationsArtifactAction[] = [
  {
    kind: "daily_brief",
    label: "Generate daily brief",
    description: "Persist a deterministic plant brief from current operation records.",
    endpoint: `${OPERATIONS_API_PREFIX}/operations/daily-brief`,
    requiredScopes: ["briefs:generate", "audit:read", "workflows:read"],
  },
  {
    kind: "quality_risk",
    label: "Build quality scenario",
    description: "Persist a quality risk scenario with workflow and evidence references.",
    endpoint: `${OPERATIONS_API_PREFIX}/operations/risk-scenarios/quality`,
    requiredScopes: ["quality:read", "workflows:read", "audit:read"],
  },
  {
    kind: "maintenance_risk",
    label: "Build maintenance scenario",
    description: "Persist a maintenance risk scenario from CMMS-backed records.",
    endpoint: `${OPERATIONS_API_PREFIX}/operations/risk-scenarios/maintenance`,
    requiredScopes: ["maintenance:read", "workflows:read", "audit:read"],
  },
  {
    kind: "supplier_delay",
    label: "Build supplier scenario",
    description: "Persist a supply delay scenario with approval and workflow evidence.",
    endpoint: `${OPERATIONS_API_PREFIX}/operations/risk-scenarios/supplier-delay`,
    requiredScopes: ["supply:read", "workflows:read", "audit:read"],
  },
];

function actionForKind(kind: OperationsArtifactKind): OperationsArtifactAction {
  const action = OPERATIONS_ARTIFACT_ACTIONS.find((item) => item.kind === kind);
  if (!action) {
    throw new OperationsArtifactRequestError(`Unsupported operations artifact: ${kind}`);
  }
  return action;
}

function missingScopes(
  action: OperationsArtifactAction,
  identitySession: IdentitySessionReadModel | null,
): string[] {
  const scopes = new Set(identitySession?.scopes ?? []);
  return action.requiredScopes.filter((scope) => !scopes.has(scope));
}

export function getOperationsArtifactActionState(
  kind: OperationsArtifactKind,
  identitySession: IdentitySessionReadModel | null,
): OperationsArtifactActionState {
  const action = actionForKind(kind);

  if (!identitySession?.authenticated || !identitySession.actor_id || !identitySession.tenant_id) {
    return {
      action,
      canRun: false,
      missingScopes: action.requiredScopes,
      reason: "Requires an API-verified OIDC actor before Axis can persist artifacts.",
    };
  }

  const missing = missingScopes(action, identitySession);
  if (missing.length > 0) {
    return {
      action,
      canRun: false,
      missingScopes: missing,
      reason: `Missing required scopes: ${missing.join(", ")}`,
    };
  }

  return {
    action,
    canRun: true,
    missingScopes: [],
    reason: null,
  };
}

export function buildOperationsArtifactRequest({
  kind,
  identitySession,
  snapshot,
}: BuildOperationsArtifactRequestInput): OperationsArtifactRequest {
  const state = getOperationsArtifactActionState(kind, identitySession);

  if (!state.canRun || !identitySession?.actor_id || !identitySession.tenant_id) {
    throw new OperationsArtifactRequestError(state.reason ?? "Operations artifact is unavailable.");
  }

  const briefDate = snapshot.as_of.slice(0, 10);
  const idempotencyWindow = kind === "daily_brief" ? briefDate : "current";
  const idempotencyKey = [
    identitySession.tenant_id,
    "console",
    kind,
    idempotencyWindow,
    identitySession.actor_id,
  ].join(":");

  const body: OperationsArtifactRequestBody = {
    tenant_id: identitySession.tenant_id,
    requested_by: identitySession.actor_id,
    actor_scopes: identitySession.scopes,
    idempotency_key: idempotencyKey,
    limit: 100,
  };

  if (kind === "daily_brief") {
    body.brief_date = briefDate;
  }

  return {
    action: state.action,
    endpoint: state.action.endpoint,
    body,
  };
}

export function operationsArtifactRecordId(response: OperationsArtifactResponse): string {
  return response.brief_id ?? response.scenario_id ?? response.audit_event_id ?? "artifact";
}

export function operationsArtifactHeadline(response: OperationsArtifactResponse): string {
  return (
    response.summary_payload?.headline
    ?? response.scenario_payload?.headline
    ?? `${operationsArtifactRecordId(response)} persisted by Axis.`
  );
}
