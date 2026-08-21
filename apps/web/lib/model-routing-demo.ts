import type {
  ManufacturingProvenance,
  OverviewMetric,
  PlatformStatus,
} from "./platform-overview";

export type ModelProviderOption = {
  provider_id: string;
  display_name: string;
  provider_type: string;
  hosting_boundary: string;
  status: string;
  egress_mode: string;
  cost_basis: string;
  allowed_policies: string[];
  notes: string[];
};

export type ModelRouteTelemetry = {
  route_id: string;
  agent_id: string;
  agent_name: string;
  domain: string;
  provider_id: string;
  provider_name: string;
  model: string;
  model_policy: string;
  prompt_classification: string;
  data_boundary: string;
  external_egress_requested: boolean;
  external_egress_allowed: boolean;
  egress_decision: string;
  decision_reason: string;
  route_status: PlatformStatus;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_eur: number;
  latency_ms: number;
  cost_center: string;
  required_permissions: string[];
  evidence_refs: string[];
  audit_event_id: string;
  observability_events: string[];
};

export type ModelRoutingFilterOptions = {
  domains: string[];
  providers: string[];
  model_policies: string[];
  egress_decisions: string[];
  statuses: PlatformStatus[];
};

export type ManufacturingModelRouting = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  routing_status: PlatformStatus;
  metrics: OverviewMetric[];
  filter_options: ModelRoutingFilterOptions;
  provider_options: ModelProviderOption[];
  routes: ModelRouteTelemetry[];
  budget_notes: string[];
  observability_notes: string[];
};

export type ModelRoutingFilters = {
  domain: string;
  provider: string;
  decision: string;
};

export const allModelRoutingFilter = "all";

export function formatModelRoutingLabel(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replaceAll(":", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function filterModelRoutes(
  routing: ManufacturingModelRouting,
  filters: ModelRoutingFilters,
): ModelRouteTelemetry[] {
  return routing.routes.filter((route) => {
    const domainMatches =
      filters.domain === allModelRoutingFilter || route.domain === filters.domain;
    const providerMatches =
      filters.provider === allModelRoutingFilter || route.provider_id === filters.provider;
    const decisionMatches =
      filters.decision === allModelRoutingFilter || route.egress_decision === filters.decision;

    return domainMatches && providerMatches && decisionMatches;
  });
}

export function findModelRouteById(
  routing: ManufacturingModelRouting,
  routeId: string,
): ModelRouteTelemetry {
  return routing.routes.find((route) => route.route_id === routeId) ?? routing.routes[0];
}

export function countBlockedModelRoutes(routing: ManufacturingModelRouting): number {
  return routing.routes.filter((route) => route.egress_decision === "blocked_by_default").length;
}

export function sumEstimatedModelCost(routing: ManufacturingModelRouting): number {
  return routing.routes.reduce((total, route) => total + route.estimated_cost_eur, 0);
}

export function formatEuroCost(value: number): string {
  return `EUR ${value.toFixed(2)}`;
}
