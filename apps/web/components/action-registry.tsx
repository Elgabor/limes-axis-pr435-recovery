"use client";

import { useMemo, useState } from "react";
import { FileText, Filter, RotateCcw, Send, ShieldCheck } from "lucide-react";

import {
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import {
  parseActionRunPersistenceResult,
  parseManufacturingActionRegistry,
} from "@/lib/runtime-contracts/actions";
import {
  actionRunWorkflowSignalLabel,
  allActionFilter,
  buildActionRunRequest,
  countApprovalGatedActions,
  filterActions,
  findActionById,
  formatActionLabel,
  formatSchemaFields,
  type ActionFilters,
  type ActionRegistryEntry,
  type ActionRunPersistenceResult,
  type ManufacturingActionRegistry,
} from "@/lib/action-demo";
import { formatContextPath, formatNumber, formatTimestamp } from "@/lib/format";
import { deriveGovernedActor } from "@/lib/governed-action";
import {
  platformStatusClass,
  platformStatusLabel,
} from "@/lib/platform-overview";
import { deriveSourceState } from "@/lib/source-state";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useIdentitySession } from "@/lib/use-identity-session";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  resolveConsoleTenantScope,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";

type ActionRunSource = "api";

type LocalActionRunResult = {
  source: ActionRunSource;
  status: string;
  actionRunId: string;
  idempotencyKey: string;
  detail: string;
  auditEventType?: string;
  permissionDetail?: string;
  workflowSignalDetail?: string;
};

const defaultFilters: ActionFilters = {
  domain: allActionFilter,
  riskLevel: allActionFilter,
  approvalMode: allActionFilter,
  status: allActionFilter,
};

function riskClass(action: ActionRegistryEntry): string {
  if (action.definition.risk_level === "critical" || action.definition.risk_level === "high") {
    return "signal-action-required";
  }

  return action.definition.risk_level === "medium" ? "signal-watch" : "signal-ready";
}

function approvalClass(action: ActionRegistryEntry): string {
  return action.definition.approval_mode === "not_required" ? "signal-ready" : "signal-watch";
}

function PayloadRows({ payload }: { payload: Record<string, string> }) {
  return (
    <div className="grid min-w-0 gap-2">
      {Object.entries(payload).map(([key, value]) => (
        <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5" key={key}>
          <p className="eyebrow m-0">{formatActionLabel(key)}</p>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{value}</p>
        </div>
      ))}
    </div>
  );
}

export function ActionRegistry() {
  const identity = useIdentitySession();
  const tenantScope = resolveConsoleTenantScope(identity.data);
  const tenantId = tenantScope.tenantId;
  const {
    data: registry,
    errorRequestId: registryErrorRequestId,
    source,
  } = useAxisQuery<ManufacturingActionRegistry>(
    buildTenantScopedPath(
      `${OPERATIONS_API_PREFIX}/actions`,
      tenantId ?? DEMO_TENANT_ID,
    ),
    {
      enabled: identity.source === "api" && tenantId !== null,
      expectedTenantId: tenantId ?? undefined,
      parse: parseManufacturingActionRegistry,
    },
  );
  const [filters, setFilters] = useState<ActionFilters>(defaultFilters);
  const [selectedActionId, setSelectedActionId] = useState("");
  const [actionRunResults, setActionRunResults] = useState<Record<string, LocalActionRunResult>>(
    {},
  );
  const [actionRunErrors, setActionRunErrors] = useState<Record<string, AxisOperatorError>>({});
  const [submittingActionId, setSubmittingActionId] = useState<string | null>(null);
  const { session } = useOidcConsoleSession();
  const { ssoBlocked } = deriveGovernedActor(identity.data ?? null, "action-registry-operator");

  const filteredActions = useMemo(
    () => (registry ? filterActions(registry, filters) : []),
    [registry, filters],
  );
  const effectiveSelectedActionId = filteredActions.some(
    (action) => action.definition.action_id === selectedActionId,
  )
    ? selectedActionId
    : (filteredActions[0]?.definition.action_id ?? registry?.actions[0]?.definition.action_id ?? "");

  const selectedAction = useMemo(
    () =>
      registry && registry.actions.length > 0
        ? findActionById(registry, effectiveSelectedActionId)
        : null,
    [registry, effectiveSelectedActionId],
  );
  const gatedActions = registry ? countApprovalGatedActions(registry) : 0;
  const selectedRunResult = selectedAction
    ? actionRunResults[selectedAction.definition.action_id]
    : undefined;
  const selectedRunError = selectedAction
    ? actionRunErrors[selectedAction.definition.action_id]
    : undefined;

  function updateFilter(filterName: keyof ActionFilters, value: string) {
    setFilters((current) => ({
      ...current,
      [filterName]: value,
    }));
  }

  function resetFilters() {
    setFilters(defaultFilters);
  }

  async function requestActionRun(action: ActionRegistryEntry) {
    if (!registry || ssoBlocked) {
      return;
    }

    const verifiedActor = identity.data?.actor_id
      ? { actorId: identity.data.actor_id, scopes: identity.data.scopes }
      : undefined;
    const request = buildActionRunRequest(registry, action, verifiedActor);
    setSubmittingActionId(action.definition.action_id);
    setActionRunErrors((current) => {
      const next = { ...current };
      delete next[action.definition.action_id];
      return next;
    });

    try {
      const result = await axisFetchParsedJson<ActionRunPersistenceResult>(
        buildTenantScopedPath(
          `${OPERATIONS_API_PREFIX}/actions/${action.definition.action_id}/runs`,
          registry.tenant_id,
        ),
        parseActionRunPersistenceResult,
        {
          session,
          method: "POST",
          body: request,
        },
      );
      setActionRunResults((current) => ({
        ...current,
        [action.definition.action_id]: {
          source: "api",
          status: result.status,
          actionRunId: result.action_run_id,
          idempotencyKey: result.idempotency_key,
          detail: result.idempotent_replay
            ? "Idempotent replay returned the existing action run."
            : "Persisted through the action run API.",
          auditEventType: result.audit_event_type ?? "no new audit event",
          permissionDetail: `Permission ${result.permission_decision.reason}.`,
          workflowSignalDetail: actionRunWorkflowSignalLabel(result),
        },
      }));
    } catch (caught) {
      setActionRunErrors((current) => ({
        ...current,
        [action.definition.action_id]: toAxisOperatorError(
          caught,
          "Action run API persistence is unavailable.",
        ),
      }));
    } finally {
      setSubmittingActionId(null);
    }
  }

  if (identity.source === "unavailable") {
    return (
      <ErrorPanel
        detail="The action registry is not loaded until the current actor and tenant are verified."
        endpoint="/identity/session"
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (identity.source === "api" && !tenantId) {
    return (
      <ErrorPanel
        detail="The authenticated identity response does not contain a tenant."
        endpoint="/identity/session"
        title="Authenticated tenant missing"
      />
    );
  }

  if (!registry) {
    if (source === "loading") {
      return <LoadingPanel layout="detail" />;
    }

    return (
      <ErrorPanel
        detail="Axis did not receive API-backed action records. Local fallback action records are disabled."
        endpoint={`${OPERATIONS_API_PREFIX}/actions`}
        reference={registryErrorRequestId ?? undefined}
        title="Action API unavailable"
      />
    );
  }

  if (registry.actions.length === 0) {
    return (
      <div className="grid gap-3">
        <div className="flex justify-end">
          <SourcePill
            state={deriveSourceState(source, true, registry.provenance)}
            subject="action registry"
          />
        </div>
        <EmptyPanel
          detail="Governed actions will appear here after they are registered for this tenant."
          icon={FileText}
          title="No actions registered yet"
        />
      </div>
    );
  }

  if (!selectedAction) {
    return (
      <ErrorPanel
        detail="The action API responded without registry records for this tenant."
        endpoint={`${OPERATIONS_API_PREFIX}/actions`}
        title="Action API returned no records"
      />
    );
  }

  return (
    <div className="grid min-w-0 gap-4">
      <div
        aria-label="Action source and registry status"
        className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
      >
        <p className="m-0 min-w-0 text-sm leading-snug break-words text-muted">
          {formatContextPath(
            registry.plant_name,
            registry.scenario,
            `schema ${registry.schema_version}`,
          )}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SourcePill
            state={deriveSourceState(source, Boolean(registry), registry.provenance)}
            subject="action registry"
          />
          <span className={`status-pill ${platformStatusClass(registry.registry_status)}`}>
            <FileText size={15} />
            {platformStatusLabel(registry.registry_status)}
          </span>
          <span className="font-mono text-[13px] break-words text-muted">{formatTimestamp(registry.as_of)}</span>
        </div>
      </div>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4 [&>*]:min-w-0">
        {registry.metrics.map((metric) => (
          <article className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5 min-h-[120px]" key={metric.label}>
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
              <p className="eyebrow m-0">{metric.label}</p>
              <span className={`status-pill ${platformStatusClass(metric.status)}`}>
                {platformStatusLabel(metric.status)}
              </span>
            </div>
            <p className="font-display mx-0 mt-3 mb-1.5 text-2xl tabular-nums break-words text-ink">{metric.value}</p>
            <p className="m-0 text-xs leading-relaxed text-muted break-words">{metric.detail}</p>
          </article>
        ))}
      </div>

      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow m-0">Filters</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">Action registry</h2>
        </div>
        <div className="grid w-full min-w-0 gap-2.5 sm:flex sm:w-auto sm:flex-wrap sm:items-end sm:justify-end">
          <Field label="Domain">
            <Select
              value={filters.domain}
              onChange={(event) => updateFilter("domain", event.target.value)}
            >
              <option value={allActionFilter}>All domains</option>
              {registry.filter_options.domains.map((domain) => (
                <option key={domain} value={domain}>
                  {domain}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Risk">
            <Select
              value={filters.riskLevel}
              onChange={(event) => updateFilter("riskLevel", event.target.value)}
            >
              <option value={allActionFilter}>All risks</option>
              {registry.filter_options.risk_levels.map((risk) => (
                <option key={risk} value={risk}>
                  {formatActionLabel(risk)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Approval">
            <Select
              value={filters.approvalMode}
              onChange={(event) => updateFilter("approvalMode", event.target.value)}
            >
              <option value={allActionFilter}>All modes</option>
              {registry.filter_options.approval_modes.map((mode) => (
                <option key={mode} value={mode}>
                  {formatActionLabel(mode)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Status">
            <Select
              value={filters.status}
              onChange={(event) => updateFilter("status", event.target.value)}
            >
              <option value={allActionFilter}>All statuses</option>
              {registry.filter_options.statuses.map((status) => (
                <option key={status} value={status}>
                  {formatActionLabel(status)}
                </option>
              ))}
            </Select>
          </Field>
          <button className="icon-button" onClick={resetFilters} title="Reset action filters" type="button">
            <RotateCcw size={17} />
          </button>
        </div>
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(310px,0.46fr)_minmax(0,1fr)] [&>*]:min-w-0">
        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow m-0">Actions</p>
              <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{formatNumber(filteredActions.length)} visible</h2>
            </div>
            <span className="status-pill signal-watch">
              <Filter size={15} />
              {formatNumber(gatedActions)} gated
            </span>
          </div>
          {filteredActions.length === 0 ? (
            <EmptyPanel
              action={{ label: "Reset filters", onClick: resetFilters }}
              detail="Adjust or reset the domain, risk, approval and status filters to see registered actions."
              title="No actions match the current filters"
            />
          ) : null}
          <div className="grid">
            {filteredActions.map((action) => {
              const isSelected =
                action.definition.action_id === selectedAction.definition.action_id;

              return (
                <button
                  aria-pressed={isSelected}
                  className={`grid w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 border-0 border-t border-line/60 bg-transparent px-2.5 py-3.5 text-left text-ink transition-colors first:border-t-0 hover:bg-ink/4 dark:border-white/10 dark:hover:bg-white/6${isSelected ? " bg-signal/10 shadow-[inset_2px_0_0_rgb(var(--signal))] dark:bg-signal/15" : ""}`}
                  key={action.definition.action_id}
                  onClick={() => setSelectedActionId(action.definition.action_id)}
                  type="button"
                >
                  <span>
                    <span className="m-0 font-medium text-ink break-words">{action.definition.display_name}</span>
                    <span className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                      {action.definition.domain} / {action.owner_role}
                    </span>
                    <span className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{formatActionLabel(action.status)}</span>
                  </span>
                  <span className={`status-pill ${riskClass(action)}`}>
                    {formatActionLabel(action.definition.risk_level)}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 grid gap-4">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow m-0">{selectedAction.definition.domain}</p>
              <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{selectedAction.definition.display_name}</h2>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedAction.description}</p>
            </div>
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
              <span className={`status-pill ${riskClass(selectedAction)}`}>
                {formatActionLabel(selectedAction.definition.risk_level)}
              </span>
              <span className={`status-pill ${approvalClass(selectedAction)}`}>
                {formatActionLabel(selectedAction.definition.approval_mode)}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3.5 border-y border-line/60 py-3.5 xl:grid-cols-4 dark:border-white/10 [&>*]:min-w-0">
            <div>
              <p className="eyebrow m-0">Action ID</p>
              <p className="m-0 font-medium text-ink break-words font-mono text-[13px]">{selectedAction.definition.action_id}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{formatActionLabel(selectedAction.status)}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Owner</p>
              <p className="m-0 font-medium text-ink break-words">{selectedAction.owner_role}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">Approval role {selectedAction.policy.approval_role}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Runtime</p>
              <p className="m-0 font-medium text-ink break-words">{selectedAction.policy.runtime_adapter}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{formatActionLabel(selectedAction.policy.execution_mode)}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Autonomy</p>
              <p className="m-0 font-medium text-ink break-words">{selectedAction.policy.autonomy_ceiling}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">Ceiling for agent draft/execution</p>
            </div>
          </div>

          <div className="grid gap-4 border-y border-line/60 py-3.5 dark:border-white/10 lg:grid-cols-[minmax(0,0.65fr)_minmax(260px,1fr)] [&>*]:min-w-0">
            <section>
              <p className="eyebrow m-0">Policy</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">{selectedAction.policy.model_egress_policy}</span>
                <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">{selectedAction.policy.audit_event_type}</span>
                <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">
                  idempotency {selectedAction.policy.idempotency_required ? "required" : "optional"}
                </span>
                <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">
                  dry-run {selectedAction.policy.dry_run_supported ? "supported" : "blocked"}
                </span>
              </div>
            </section>
            <section>
              <p className="eyebrow m-0">Required Permissions</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {selectedAction.definition.required_permissions.map((permission) => (
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={permission}>
                    {permission}
                  </span>
                ))}
              </div>
            </section>
          </div>

          <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
            <section>
              <p className="eyebrow m-0">Connected Agents</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {selectedAction.connected_agents.map((agent) => (
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={agent}>
                    {agent}
                  </span>
                ))}
              </div>
            </section>
            <section>
              <p className="eyebrow m-0">Workflow Bindings</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {selectedAction.workflow_bindings.map((workflow) => (
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={workflow}>
                    {workflow}
                  </span>
                ))}
              </div>
            </section>
            <section>
              <p className="eyebrow m-0">Approval Refs</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {selectedAction.approval_refs.length > 0 ? (
                  selectedAction.approval_refs.map((approval) => (
                    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={approval}>
                      {approval}
                    </span>
                  ))
                ) : (
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">not_required</span>
                )}
              </div>
            </section>
          </div>

          <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
            <section>
              <p className="eyebrow m-0">Input Schema</p>
              <ul className="mx-0 mt-2.5 mb-0 grid list-disc gap-2 pl-5 text-sm leading-snug text-muted">
                {formatSchemaFields(selectedAction.definition.input_schema).map((field) => (
                  <li key={field}>{field}</li>
                ))}
              </ul>
            </section>
            <section>
              <p className="eyebrow m-0">Output Schema</p>
              <ul className="mx-0 mt-2.5 mb-0 grid list-disc gap-2 pl-5 text-sm leading-snug text-muted">
                {formatSchemaFields(selectedAction.definition.output_schema).map((field) => (
                  <li key={field}>{field}</li>
                ))}
              </ul>
            </section>
            <section>
              <p className="eyebrow m-0">Side Effects</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedAction.side_effects}</p>
            </section>
          </div>

          <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
            <section>
              <p className="eyebrow m-0">Guardrails</p>
              <ul className="mx-0 mt-2.5 mb-0 grid list-disc gap-2 pl-5 text-sm leading-snug text-muted">
                {selectedAction.guardrails.map((guardrail) => (
                  <li key={guardrail}>{guardrail}</li>
                ))}
              </ul>
            </section>
            <section>
              <p className="eyebrow m-0">Validation Checks</p>
              <ul className="mx-0 mt-2.5 mb-0 grid list-disc gap-2 pl-5 text-sm leading-snug text-muted">
                {selectedAction.validation_checks.map((check) => (
                  <li key={check}>{check}</li>
                ))}
              </ul>
            </section>
            <section>
              <p className="eyebrow m-0">Blocked Conditions</p>
              <ul className="mx-0 mt-2.5 mb-0 grid list-disc gap-2 pl-5 text-sm leading-snug text-muted">
                {selectedAction.blocked_conditions.map((condition) => (
                  <li key={condition}>{condition}</li>
                ))}
              </ul>
            </section>
          </div>

          <section className="grid min-w-0 gap-3 border-t border-line/60 pt-3.5 dark:border-white/10">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow m-0">Payload Preview</p>
                <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">API dry-run payload</h3>
              </div>
              <div className="inline-flex flex-wrap items-center justify-end gap-2.5">
                {ssoBlocked ? (
                  <p className="m-0 flex items-center gap-2 text-sm text-muted" role="status">
                    <ShieldCheck aria-hidden="true" className="shrink-0 text-signal" size={15} />
                    Sign in with SSO to request governed action runs.
                  </p>
                ) : (
                  <button
                    className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60"
                    disabled={submittingActionId === selectedAction.definition.action_id}
                    onClick={() => void requestActionRun(selectedAction)}
                    type="button"
                  >
                    <Send size={16} />
                    {submittingActionId === selectedAction.definition.action_id
                      ? "Requesting"
                      : "Request dry-run"}
                  </button>
                )}
                {!ssoBlocked ? <ShieldCheck size={18} /> : null}
              </div>
            </div>
            <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
              <section>
                <p className="eyebrow m-0">Sample Input</p>
                <PayloadRows payload={selectedAction.sample_input} />
              </section>
              <section>
                <p className="eyebrow m-0">Sample Output</p>
                <PayloadRows payload={selectedAction.sample_output} />
              </section>
            </div>
            {selectedRunResult ? (
              <section className="grid gap-4 border-t border-line/60 pt-3.5 dark:border-white/10 lg:grid-cols-[minmax(220px,0.4fr)_minmax(0,1fr)] [&>*]:min-w-0" aria-label="Action run result">
                <div>
                  <p className="eyebrow m-0">Persisted Action Run</p>
                  <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">
                    {formatActionLabel(selectedRunResult.status)}
                  </h3>
                  <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedRunResult.detail}</p>
                </div>
                <div className="grid min-w-0 gap-2">
                  <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                    <p className="eyebrow m-0">Run ID</p>
                    <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">{selectedRunResult.actionRunId}</p>
                  </div>
                  <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                    <p className="eyebrow m-0">Idempotency</p>
                    <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">{selectedRunResult.idempotencyKey}</p>
                  </div>
                  {selectedRunResult.auditEventType ? (
                    <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                      <p className="eyebrow m-0">Audit</p>
                      <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedRunResult.auditEventType}</p>
                    </div>
                  ) : null}
                  {selectedRunResult.permissionDetail ? (
                    <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                      <p className="eyebrow m-0">Permission</p>
                      <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedRunResult.permissionDetail}</p>
                    </div>
                  ) : null}
                  {selectedRunResult.workflowSignalDetail ? (
                    <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                      <p className="eyebrow m-0">Workflow Signal</p>
                      <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedRunResult.workflowSignalDetail}</p>
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}
            {selectedRunError ? (
              <section className="border-t border-line/60 pt-3.5 dark:border-white/10" aria-label="Action run persistence error">
                <ErrorPanel
                  detail={selectedRunError.message}
                  reference={selectedRunError.requestId ?? undefined}
                  title="Action run persistence unavailable"
                />
              </section>
            ) : null}
          </section>
        </section>
      </div>

      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
        <p className="eyebrow m-0">Registry Notes</p>
        <div className="grid min-w-0 gap-2.5">
          {registry.registry_notes.map((note) => (
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" key={note}>
              {note}
            </p>
          ))}
        </div>
      </section>
    </div>
  );
}
