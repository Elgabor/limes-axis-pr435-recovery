import type { ReactNode } from "react";

import { Eyebrow } from "@/components/ui/eyebrow";

export interface PageHeaderProps {
  eyebrow: string;
  title: string;
  description?: string;
  /** Status pills rendered next to the title. */
  status?: ReactNode;
  /** Primary page actions, right-aligned. */
  actions?: ReactNode;
  /** Secondary metadata row under the description (fetch time, tenant, …). */
  meta?: ReactNode;
}

/** Two-tone title device shared with the marketing pages: lead word in Signal. */
function splitTitle(title: string): { lead: string; rest: string } {
  const [lead = "", ...rest] = title.trim().split(/\s+/);
  return { lead, rest: rest.join(" ") };
}

/** The single page header — one per page, fed from `strings.pages`. */
export function PageHeader({ eyebrow, title, description, status, actions, meta }: PageHeaderProps) {
  const { lead, rest } = splitTitle(title);

  return (
    <header className="flex min-w-0 flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <Eyebrow accent>{eyebrow}</Eyebrow>
        <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-3">
          {/* 20px, not 26px: the page title sits above a description, a meta
              row and status pills — at display size the header became a hero
              band on every route. */}
          <h1 className="font-display m-0 text-xl font-[560] text-ink">
            {rest ? (
              <>
                <span className="text-signal">{lead} </span>
                {rest}
              </>
            ) : (
              lead
            )}
          </h1>
          {status}
        </div>
        {description ? (
          <p className="mx-0 mt-1.5 mb-0 max-w-3xl text-sm leading-snug text-muted">
            {description}
          </p>
        ) : null}
        {meta ? (
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            {meta}
          </div>
        ) : null}
      </div>
      {actions ? (
        <div aria-label="Page actions" className="flex flex-wrap items-center justify-end gap-2">
          {actions}
        </div>
      ) : null}
    </header>
  );
}
