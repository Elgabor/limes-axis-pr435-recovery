"use client";

import type { ReactNode } from "react";

import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { ErrorPanel, LoadingPanel } from "@/components/ui/states";
import { formatConnectorLabel } from "@/lib/connectors-demo";
import { formatDateTime } from "@/lib/format";
import { strings } from "@/lib/strings";
import type { AxisQuerySource } from "@/lib/use-axis-query";
import type { ConnectorRegistries } from "@/lib/use-connector-registries";

/*
 * Governance & Evidence tab: credential handles, credential leases, egress
 * policies and the evidence-invariant summary as plain sections with Inspect
 * drawers — the replacement for the old invariant-tile wall. Each section
 * degrades independently when its registry endpoint fails.
 */

function governanceStatusClass(status: string): string {
  const normalized = status.toLowerCase();
  if (["active", "healthy", "valid", "passed", "compliant", "enabled", "rotated"].includes(normalized)) {
    return "signal-ready";
  }
  if (["failed", "revoked", "expired", "breached", "violation", "invalid"].includes(normalized)) {
    return "signal-action-required";
  }
  return "signal-watch";
}

function Section({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children: ReactNode;
}) {
  return (
    <section className="grid content-start gap-2.5">
      <div className="grid gap-1">
        <Eyebrow>{title}</Eyebrow>
        <p className="m-0 text-sm text-muted">{detail}</p>
      </div>
      {children}
    </section>
  );
}

function SectionState({
  source,
  errorTitle,
  errorRequestId,
  isEmpty,
  emptyLabel,
  children,
}: {
  source: AxisQuerySource;
  errorTitle: string;
  errorRequestId?: string | null;
  isEmpty: boolean;
  emptyLabel: string;
  children: ReactNode;
}) {
  if (source === "loading") {
    return <LoadingPanel rows={2} />;
  }
  if (source === "unavailable" && isEmpty) {
    return <ErrorPanel reference={errorRequestId ?? undefined} title={errorTitle} />;
  }
  if (isEmpty) {
    return <p className="m-0 text-sm text-muted">{emptyLabel}</p>;
  }
  if (source === "unavailable") {
    return (
      <>
        <p className="m-0 text-sm text-warning" role="status">
          Live refresh failed. Showing the last validated data.
        </p>
        {children}
      </>
    );
  }
  return <>{children}</>;
}

function RecordRow({
  title,
  status,
  record,
  children,
}: {
  title: string;
  status: string;
  record: Record<string, unknown>;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-3 rounded-2xl border border-line p-4 dark:border-white/10">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-ink">{title}</span>
        <span className="flex items-center gap-3">
          <span className={`status-pill ${governanceStatusClass(status)}`}>
            {formatConnectorLabel(status)}
          </span>
          <InspectDrawer record={record} title={title} />
        </span>
      </div>
      <DetailGrid>{children}</DetailGrid>
    </div>
  );
}

export function ConnectorGovernance({
  connectorId,
  registries,
}: {
  connectorId: string;
  registries: ConnectorRegistries;
}) {
  const copy = strings.connectors.governance;
  const handles = (registries.credentialHandles.data?.handles ?? []).filter(
    (handle) => handle.connector_id === connectorId,
  );
  const leases = (registries.credentialLeases.data?.leases ?? []).filter(
    (lease) => lease.connector_id === connectorId,
  );
  const egressPolicies = (registries.egressPolicies.data?.policies ?? []).filter(
    (policy) => policy.connector_id === connectorId,
  );
  const invariantReport = registries.evidenceInvariants.data;

  return (
    <div className="grid content-start gap-6">
      <Section detail={copy.handles.detail} title={copy.handles.title}>
        <SectionState
          emptyLabel={copy.handles.empty}
          errorRequestId={registries.credentialHandles.errorRequestId}
          errorTitle={copy.handles.error}
          isEmpty={handles.length === 0}
          source={registries.credentialHandles.source}
        >
          <div className="grid gap-2.5">
            {handles.map((handle) => (
              <RecordRow
                key={handle.handle_id}
                record={handle}
                status={handle.status}
                title={handle.display_name}
              >
                <KeyValueRow label="Reference" mono>
                  {handle.secret_ref}
                </KeyValueRow>
                <KeyValueRow label="Rotation">
                  {formatConnectorLabel(handle.rotation_status)} / every{" "}
                  {handle.rotation_interval_days} days
                </KeyValueRow>
              </RecordRow>
            ))}
          </div>
        </SectionState>
      </Section>

      <Section detail={copy.leases.detail} title={copy.leases.title}>
        <SectionState
          emptyLabel={copy.leases.empty}
          errorRequestId={registries.credentialLeases.errorRequestId}
          errorTitle={copy.leases.error}
          isEmpty={leases.length === 0}
          source={registries.credentialLeases.source}
        >
          <div className="grid gap-2.5">
            {leases.map((lease) => (
              <RecordRow
                key={lease.lease_id}
                record={lease}
                status={lease.status}
                title={lease.lease_purpose}
              >
                <KeyValueRow label="Lease" mono>
                  {lease.lease_id}
                </KeyValueRow>
                <KeyValueRow label="Window">
                  {formatDateTime(lease.granted_at)} → {formatDateTime(lease.expires_at)}
                </KeyValueRow>
              </RecordRow>
            ))}
          </div>
        </SectionState>
      </Section>

      <Section detail={copy.egress.detail} title={copy.egress.title}>
        <SectionState
          emptyLabel={copy.egress.empty}
          errorRequestId={registries.egressPolicies.errorRequestId}
          errorTitle={copy.egress.error}
          isEmpty={egressPolicies.length === 0}
          source={registries.egressPolicies.source}
        >
          <div className="grid gap-2.5">
            {egressPolicies.map((policy) => (
              <RecordRow
                key={policy.policy_id}
                record={policy}
                status={policy.status}
                title={policy.display_name}
              >
                <KeyValueRow label="Boundary">
                  {formatConnectorLabel(policy.egress_boundary)} /{" "}
                  {formatConnectorLabel(policy.policy_mode)}
                </KeyValueRow>
                <KeyValueRow label="Profile" mono>
                  {policy.connection_profile_id}
                </KeyValueRow>
              </RecordRow>
            ))}
          </div>
        </SectionState>
      </Section>

      <Section detail={copy.invariants.detail} title={copy.invariants.title}>
        <SectionState
          emptyLabel={copy.invariants.allClear}
          errorRequestId={registries.evidenceInvariants.errorRequestId}
          errorTitle={copy.invariants.error}
          isEmpty={(invariantReport?.invariants ?? []).length === 0}
          source={registries.evidenceInvariants.source}
        >
          {invariantReport ? (
            <div className="grid gap-2.5">
              {invariantReport.invariants.map((invariant) => (
                <div
                  className="flex flex-wrap items-start justify-between gap-2 rounded-2xl border border-warning/40 bg-warning/8 p-4"
                  key={`${invariant.evidence_type}-${invariant.subject_id}-${invariant.reason}`}
                >
                  <div className="grid min-w-0 gap-0.5">
                    <span className="text-sm font-medium text-ink">
                      {formatConnectorLabel(invariant.evidence_type)} /{" "}
                      {formatConnectorLabel(invariant.reason)}
                    </span>
                    <span className="text-xs text-muted">{invariant.detail}</span>
                  </div>
                  <InspectDrawer
                    record={invariant}
                    title={`${invariant.evidence_type} invariant`}
                  />
                </div>
              ))}
            </div>
          ) : null}
        </SectionState>
      </Section>
    </div>
  );
}
