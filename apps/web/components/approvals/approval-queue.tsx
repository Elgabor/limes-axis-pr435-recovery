"use client";

import { useEffect, useRef, type KeyboardEvent } from "react";
import { ChevronRight, Search, X } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { controlClassName } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { approvalRiskClass, type ApprovalInboxItem } from "@/lib/approval-demo";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/strings";

export type ApprovalQueueFilters = {
  search: string;
  risk: "all" | "high" | "medium" | "low";
  domain: string;
};

export function filterApprovalQueue(
  approvals: ApprovalInboxItem[],
  filters: ApprovalQueueFilters,
  labelDomain: (domain: string) => string,
) {
  const query = filters.search.trim().toLowerCase();
  return approvals.filter((approval) => (
    (filters.risk === "all" || approval.risk_level === filters.risk)
    && (!filters.domain || approval.domain === filters.domain)
    && (!query || [
      approval.action,
      approval.summary,
      approval.owner_role,
      approval.requested_by,
      approval.workflow_id,
      approval.approval_id,
      approval.domain,
      labelDomain(approval.domain),
    ].join(" ").toLowerCase().includes(query))
  ));
}

export function ApprovalQueue({
  approvals,
  allApprovals,
  selectedApprovalId,
  filters,
  labelDomain,
  onFilterChange,
  onReset,
  onSelect,
}: {
  approvals: ApprovalInboxItem[];
  allApprovals: ApprovalInboxItem[];
  selectedApprovalId?: string;
  filters: ApprovalQueueFilters;
  labelDomain: (domain: string) => string;
  onFilterChange: (change: Partial<ApprovalQueueFilters>) => void;
  onReset: () => void;
  onSelect: (approvalId: string, pushHistory: boolean) => void;
}) {
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());
  const searchRef = useRef<HTMLInputElement>(null);

  // Let the native field retain keystrokes while Next commits URL updates.
  // External resets and browser history still restore the URL's search value.
  useEffect(() => {
    if (searchRef.current && document.activeElement !== searchRef.current) {
      searchRef.current.value = filters.search;
    }
  }, [filters.search]);
  useEffect(() => {
    const restoreSearch = () => {
      if (searchRef.current) {
        searchRef.current.value = new URLSearchParams(window.location.search).get("q") ?? "";
      }
    };
    window.addEventListener("popstate", restoreSearch);
    return () => window.removeEventListener("popstate", restoreSearch);
  }, []);
  const domains = Array.from(new Set(allApprovals.map((approval) => approval.domain)));
  const filtered = Boolean(filters.search || filters.risk !== "all" || filters.domain);
  const copy = strings.approvals.queue;

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const index = approvals.findIndex((approval) => (
      itemRefs.current.get(approval.approval_id) === document.activeElement
    ));
    if (index < 0) return;
    event.preventDefault();
    const nextIndex = event.key === "ArrowDown"
      ? Math.min(index + 1, approvals.length - 1)
      : Math.max(index - 1, 0);
    const next = approvals[nextIndex];
    if (next && nextIndex !== index) {
      onSelect(next.approval_id, false);
      itemRefs.current.get(next.approval_id)?.focus();
    }
  }

  return (
    <Card className="grid content-start gap-4">
      <h2 className="font-display m-0 text-lg text-ink outline-none" data-queue-heading tabIndex={-1}>
        {copy.title}
      </h2>
      <div aria-label={copy.filters} className="grid gap-3" role="group">
        <label className="relative block">
          <span className="sr-only">{copy.search}</span>
          <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" size={16} />
          <input
            className={cn(controlClassName, "min-h-11 pl-9")}
            defaultValue={filters.search}
            onChange={(event) => onFilterChange({ search: event.target.value })}
            placeholder={copy.searchPlaceholder}
            type="search"
            ref={searchRef}
          />
        </label>
        <div className="grid min-w-0 grid-cols-2 gap-3">
          <Field label={copy.risk}>
            <Select className="min-h-11" onChange={(event) => onFilterChange({ risk: event.target.value as ApprovalQueueFilters["risk"] })} value={filters.risk}>
              <option value="all">{copy.allRisks}</option>
              <option value="high">High risk</option>
              <option value="medium">Medium risk</option>
              <option value="low">Low risk</option>
            </Select>
          </Field>
          <Field label={copy.domain}>
            <Select className="min-h-11" onChange={(event) => onFilterChange({ domain: event.target.value })} value={filters.domain}>
              <option value="">{copy.allDomains}</option>
              {filters.domain && !domains.includes(filters.domain) ? (
                <option value={filters.domain}>{labelDomain(filters.domain)}</option>
              ) : null}
              {domains.map((domain) => <option key={domain} value={domain}>{labelDomain(domain)}</option>)}
            </Select>
          </Field>
        </div>
      </div>
      <div className="flex min-h-6 flex-wrap items-center justify-between gap-2">
        <p aria-live="polite" className="m-0 text-xs tabular-nums text-muted" role="status">
          {approvals.length} of {allApprovals.length} pending
        </p>
        {filtered ? (
          <button className="inline-flex min-h-8 cursor-pointer items-center gap-1 text-xs font-medium text-signal" onClick={() => {
              if (searchRef.current) searchRef.current.value = "";
              onReset();
            }} type="button">
            <X aria-hidden="true" size={13} />{copy.clear}
          </button>
        ) : null}
      </div>
      <div className="grid gap-2" onKeyDown={handleKeyDown}>
        {approvals.map((approval) => {
          const selected = approval.approval_id === selectedApprovalId;
          return (
            <button
              aria-pressed={selected}
              className={cn(
                "grid w-full min-w-0 cursor-pointer gap-2 rounded-xl border px-3 py-3 text-left transition-colors",
                selected ? "border-signal/60 bg-tint-100 dark:bg-signal/15" : "border-line bg-transparent hover:border-signal/40 hover:bg-tint-50 dark:border-white/10 dark:hover:bg-white/5",
              )}
              data-approval-id={approval.approval_id}
              key={approval.approval_id}
              onClick={() => onSelect(approval.approval_id, true)}
              ref={(element) => {
                if (element) itemRefs.current.set(approval.approval_id, element);
                else itemRefs.current.delete(approval.approval_id);
              }}
              type="button"
            >
              <span className="flex min-w-0 items-start justify-between gap-2">
                <span className="min-w-0 text-sm leading-snug font-medium break-words text-ink">{approval.action}</span>
                <ChevronRight aria-hidden="true" className="mt-0.5 shrink-0 text-muted" size={16} />
              </span>
              <span className="text-xs break-words text-muted">{labelDomain(approval.domain)} · {approval.owner_role}</span>
              <span className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-muted">Due {approval.due}</span>
                <span className={`status-pill ${approvalRiskClass(approval.risk_level)}`}>{approval.risk_level} risk</span>
              </span>
            </button>
          );
        })}
        {approvals.length === 0 ? (
          <p className="m-0 rounded-xl border border-dashed border-line p-4 text-sm text-muted dark:border-white/15">
            {allApprovals.length ? copy.noMatches : strings.approvals.empty.detail}
          </p>
        ) : null}
      </div>
    </Card>
  );
}
