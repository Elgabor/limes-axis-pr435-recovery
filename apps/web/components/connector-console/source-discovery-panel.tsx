"use client";

import { useState } from "react";
import { DatabaseZap, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Input } from "@/components/ui/input";
import {
  AxisApiDecodeError,
  AxisApiError,
  axisFetch,
  axisResponseRequestId,
  readAxisResponseBody,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import {
  buildSourceDiscoveryRequest,
  buildSourceVerifyRequest,
  SOURCE_DISCOVERY_SCOPE,
} from "@/lib/connectors-console";
import type { ConnectorRegistryItem } from "@/lib/connectors-demo";
import { safeRandomUuid } from "@/lib/ids";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import {
  parseSourceDiscoveryOutcome,
  parseSourceVerificationOutcome,
  type SourceDiscoveryOutcome,
  type SourceVerificationOutcome,
} from "@/lib/runtime-contracts/connectors";
import { strings } from "@/lib/strings";
import { OPERATIONS_API_PREFIX, buildTenantScopedPath } from "@/lib/tenant-scope";
import type { ConnectorRegistries } from "@/lib/use-connector-registries";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

import { deriveGovernedActor } from "@/lib/governed-action";

import { ConnectorSourceActivationPanel } from "./source-activation-panel";

/*
 * Verify & discover for the external Postgres source connector. The API owns
 * every gate (scope, lease, egress policy, runtime bounds); this panel makes
 * prerequisites legible, prefills them from real tenant records, and renders
 * discovered tables as honest evidence with drift states — never invented.
 */

const VERIFY_ENDPOINT = `${OPERATIONS_API_PREFIX}/connectors/external-db/verify-source`;
const DISCOVER_ENDPOINT = `${OPERATIONS_API_PREFIX}/connectors/external-db/discover`;

type PendingKind = "verify" | "discover" | null;

type ActivationSelection = {
  resourceName: string;
  schemaFingerprint: string;
};

/** Operator copy per API failure class; unknown reasons stay honest. */
function sourceOperationErrorCopy(error: AxisOperatorError): string {
  const copy = strings.connectors.sourceDiscovery;
  if (error.status === 403) {
    return error.reason === `missing_scope:${SOURCE_DISCOVERY_SCOPE}`
      ? copy.deniedScope
      : copy.forbidden;
  }
  if (error.status === 404) {
    return copy.notFound;
  }
  if (error.status === 422) {
    return copy.validationFailed;
  }
  return copy.genericError;
}

function driftPillClass(driftState: string): string {
  if (driftState === "added") {
    return "signal-ready";
  }
  if (driftState === "changed") {
    return "signal-action-required";
  }
  return "status-checking";
}

function PrerequisiteRow({ met, label }: { met: boolean; label: string }) {
  const copy = strings.connectors.sourceDiscovery;
  return (
    <li className="flex min-w-0 flex-wrap items-center justify-between gap-2">
      <span className="min-w-0 break-words text-sm text-ink">{label}</span>
      <span className={`status-pill ${met ? "signal-ready" : "signal-action-required"}`}>
        {met ? copy.prerequisiteMet : copy.prerequisiteMissing}
      </span>
    </li>
  );
}

export function ConnectorSourceDiscoveryPanel({
  connector,
  identitySession,
  registries,
  tenantId,
}: {
  connector: ConnectorRegistryItem;
  identitySession: IdentitySessionReadModel | null;
  registries: ConnectorRegistries;
  tenantId: string;
}) {
  const copy = strings.connectors.sourceDiscovery;
  const activationCopy = strings.connectors.sourceActivation;
  const { session } = useOidcConsoleSession();
  const { actorId, ssoBlocked } = deriveGovernedActor(
    identitySession,
    "connector-console-operator",
  );

  const connectorId = connector.manifest.connector_id;
  const activeLeases =
    registries.credentialLeases.data?.leases.filter(
      (lease) => lease.connector_id === connectorId && lease.status === "active",
    ) ?? [];
  const activePolicy = registries.egressPolicies.data?.policies.find(
    (policy) =>
      policy.connector_id === connectorId
      && policy.status === "active"
      && policy.policy_mode === "approved_private_endpoint",
  );

  const [connectionProfileId, setConnectionProfileId] = useState(
    "profile_postgres_discovery_readonly",
  );
  const [schemaName, setSchemaName] = useState("operations");
  // Registry records arrive asynchronously; references stay derived from
  // them until the operator explicitly overrides, so a slow query can never
  // freeze the form on an empty prefill.
  const [leaseOverride, setLeaseOverride] = useState<string | null>(null);
  const [policyOverride, setPolicyOverride] = useState<string | null>(null);
  const credentialLeaseId = leaseOverride ?? activeLeases[0]?.lease_id ?? "";
  const egressPolicyId = policyOverride ?? activePolicy?.policy_id ?? "";
  const [pending, setPending] = useState<PendingKind>(null);
  const [verification, setVerification] = useState<SourceVerificationOutcome | null>(null);
  const [discovery, setDiscovery] = useState<SourceDiscoveryOutcome | null>(null);
  const [error, setError] = useState<AxisOperatorError | null>(null);
  const [selectedTables, setSelectedTables] = useState<Map<string, ActivationSelection>>(
    () => new Map(),
  );

  const referencesReady =
    credentialLeaseId.trim().length > 0 && egressPolicyId.trim().length > 0;

  const blockedReason =
    discovery?.result.block_reason || verification?.result.block_reason || null;

  async function run(kind: Exclude<PendingKind, null>) {
    if (pending !== null || ssoBlocked) {
      return;
    }
    setPending(kind);
    setError(null);
    const token = safeRandomUuid();
    const path = buildTenantScopedPath(
      kind === "verify" ? VERIFY_ENDPOINT : DISCOVER_ENDPOINT,
      tenantId,
    );
    const body =
      kind === "verify"
        ? buildSourceVerifyRequest({
            tenantId,
            actorId,
            refs: { connectionProfileId, credentialLeaseId, egressPolicyId },
            token,
          })
        : buildSourceDiscoveryRequest({
            tenantId,
            actorId,
            refs: {
              connectionProfileId,
              schemaName,
              credentialLeaseId,
              egressPolicyId,
            },
            token,
          });
    try {
      const response = await axisFetch(path, { method: "POST", session, body });
      const requestId = axisResponseRequestId(response);
      const responseBody = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(path, response.status, { body: responseBody, requestId });
      }
      if (kind === "verify") {
        setVerification(parseSourceVerificationOutcome(responseBody));
        setDiscovery(null);
        setSelectedTables(new Map());
      } else {
        setDiscovery(parseSourceDiscoveryOutcome(responseBody));
        setVerification(null);
        setSelectedTables(new Map());
      }
    } catch (caught) {
      if (
        caught instanceof AxisApiError
        || caught instanceof AxisApiDecodeError
      ) {
        const operatorError = toAxisOperatorError(caught, copy.genericError);
        setError({ ...operatorError, message: sourceOperationErrorCopy(operatorError) });
      } else {
        setError({
          code: null,
          reason: null,
          message: copy.genericError,
          requestId: null,
          status: null,
        });
      }
    } finally {
      setPending(null);
    }
  }

  const discoveredTables = discovery?.result.tables ?? [];
  const observationsByTable = new Map(
    (discovery?.observations ?? []).map((entry) => [entry.table_name, entry.observation]),
  );
  const blockedCopy = copy.blocked as Record<string, string>;

  return (
    <section
      aria-label={copy.title}
      className="grid gap-3 border-t border-line/60 pt-4 dark:border-white/10"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <DatabaseZap aria-hidden="true" className="shrink-0 text-signal" size={16} />
        <Eyebrow>{copy.title}</Eyebrow>
      </div>
      <p className="m-0 max-w-prose text-sm leading-snug text-muted">{copy.detail}</p>

      <div className="grid gap-1">
        <Eyebrow>{copy.prerequisites.title}</Eyebrow>
        <ul aria-label={copy.prerequisites.title} className="m-0 grid list-none gap-1.5 p-0">
          <PrerequisiteRow met={activeLeases.length > 0} label={copy.prerequisites.lease} />
          <PrerequisiteRow met={Boolean(activePolicy)} label={copy.prerequisites.policy} />
        </ul>
      </div>

      {ssoBlocked ? (
        <p className="m-0 flex items-center gap-2 text-sm text-muted" role="status">
          <ShieldCheck aria-hidden="true" className="shrink-0 text-signal" size={15} />
          {copy.ssoGate}
        </p>
      ) : (
        <>
          <DetailGrid>
            <KeyValueRow label={copy.profileLabel}>
              <Input
                aria-label={copy.profileLabel}
                className="max-w-xs font-mono text-xs"
                onChange={(event) => setConnectionProfileId(event.target.value)}
                value={connectionProfileId}
              />
            </KeyValueRow>
            <KeyValueRow label={copy.schemaLabel}>
              <Input
                aria-label={copy.schemaLabel}
                className="max-w-xs font-mono text-xs"
                onChange={(event) => setSchemaName(event.target.value)}
                value={schemaName}
              />
            </KeyValueRow>
            <KeyValueRow label={copy.leaseLabel}>
              <Input
                aria-label={copy.leaseLabel}
                className="max-w-xs font-mono text-xs"
                onChange={(event) => setLeaseOverride(event.target.value)}
                value={credentialLeaseId}
              />
            </KeyValueRow>
            <KeyValueRow label={copy.policyLabel}>
              <Input
                aria-label={copy.policyLabel}
                className="max-w-xs font-mono text-xs"
                onChange={(event) => setPolicyOverride(event.target.value)}
                value={egressPolicyId}
              />
            </KeyValueRow>
          </DetailGrid>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={!referencesReady || pending !== null}
              loading={pending === "verify"}
              onClick={() => void run("verify")}
            >
              {pending === "verify" ? copy.verifying : copy.verifyAction}
            </Button>
            <Button
              disabled={!referencesReady || pending !== null}
              loading={pending === "discover"}
              onClick={() => void run("discover")}
              variant="secondary"
            >
              {pending === "discover" ? copy.discovering : copy.discoverAction}
            </Button>
          </div>
        </>
      )}

      {verification && verification.result.status === "source_verified" ? (
        <p
          aria-live="polite"
          className="m-0 rounded-2xl border border-line px-4 py-3 text-sm leading-snug text-ink dark:border-white/10"
          role="status"
        >
          {copy.verifiedDetail(verification.result.database_name)}
        </p>
      ) : null}

      {blockedReason ? (
        <p
          aria-live="polite"
          className="m-0 rounded-2xl border border-line px-4 py-3 text-sm leading-snug text-muted dark:border-white/10"
          role="alert"
        >
          {blockedCopy[blockedReason] ?? copy.blocked.generic}
        </p>
      ) : null}

      {discovery && discovery.result.status === "discovery_completed" ? (
        <div className="grid gap-2">
          <Eyebrow>{copy.discoveredTitle(discoveredTables.length)}</Eyebrow>
          <p className="m-0 text-xs leading-snug text-muted">{activationCopy.selectHint}</p>
          {discoveredTables.length === 0 ? (
            <div className="grid gap-1">
              <p className="m-0 text-sm font-medium text-ink">{copy.emptySource.title}</p>
              <p className="m-0 text-sm text-muted">{copy.emptySource.detail}</p>
            </div>
          ) : (
            <>
              <table
                aria-label={copy.discoveredTitle(discoveredTables.length)}
                className="w-full min-w-[560px] border-collapse text-left text-sm"
              >
                <thead>
                  <tr className="border-b border-line dark:border-white/10">
                    <th className="px-2 py-2 font-medium">
                      <span className="sr-only">{activationCopy.selectColumn}</span>
                      {activationCopy.selectColumn}
                    </th>
                    <th className="px-2 py-2 font-medium">{copy.tableColumn}</th>
                    <th className="px-2 py-2 font-medium">{copy.columnsColumn}</th>
                    <th className="px-2 py-2 font-medium">{copy.driftColumn}</th>
                  </tr>
                </thead>
                <tbody>
                  {discoveredTables.map((table) => {
                    const observation = observationsByTable.get(table.table_name);
                    const qualifiedName = `${table.schema_name}.${table.table_name}`;
                    const isSelected = selectedTables.has(qualifiedName);
                    return (
                      <tr
                        className="border-b border-line/60 last:border-b-0 dark:border-white/10"
                        key={table.table_name}
                      >
                        <td className="px-2 py-2 align-top">
                          <input
                            aria-label={`${activationCopy.selectColumn}: ${qualifiedName}`}
                            checked={isSelected}
                            className="-m-2 size-4 cursor-pointer p-2 accent-[rgb(var(--signal))]"
                            onChange={(event) =>
                              setSelectedTables((current) => {
                                const next = new Map(current);
                                if (event.target.checked) {
                                  next.set(qualifiedName, {
                                    resourceName: qualifiedName,
                                    schemaFingerprint: table.column_fingerprint,
                                  });
                                } else {
                                  next.delete(qualifiedName);
                                }
                                return next;
                              })
                            }
                            type="checkbox"
                          />
                        </td>
                        <td className="px-2 py-2 font-mono text-xs break-all">
                          {table.schema_name}.{table.table_name}
                        </td>
                        <td className="px-2 py-2 text-xs break-all text-muted">
                          {table.column_names.length > 0 ? table.column_names.join(", ") : "—"}
                          {table.columns_truncated ? ` (${copy.columnsTruncated})` : ""}
                        </td>
                        <td className="px-2 py-2">
                          {observation ? (
                            <span className={`status-pill ${driftPillClass(observation.drift_state)}`}>
                              {(copy.drift as Record<string, string>)[observation.drift_state]
                              ?? observation.drift_state}
                            </span>
                          ) : (
                            <span className="text-xs text-muted">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {discovery.result.tables_truncated ? (
                <p className="m-0 text-xs leading-snug text-muted">{copy.truncatedDetail}</p>
              ) : null}
              <p className="m-0 text-xs leading-snug text-muted">{copy.observationNote}</p>
            </>
          )}
          {selectedTables.size > 0 ? (
            <ConnectorSourceActivationPanel
              identitySession={identitySession}
              onActivated={() => {
                // The journey completes on success: the toast plus the durable
                // bindings section carry the outcome, so the next pass starts
                // from a clean slate instead of offering already-bound tables.
                setDiscovery(null);
                setVerification(null);
                setSelectedTables(new Map());
              }}
              refs={{
                connectionProfileId,
                credentialLeaseId,
                egressPolicyId,
              }}
              selections={[...selectedTables.values()]}
              tenantId={tenantId}
            />
          ) : null}
        </div>
      ) : null}

      {error ? <InlineOperatorError error={error} /> : null}
    </section>
  );
}
