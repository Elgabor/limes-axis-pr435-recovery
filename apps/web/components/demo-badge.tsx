"use client";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { ManufacturingOverview } from "@/lib/platform-overview";
import { strings } from "@/lib/strings";
import { buildTenantScopedPath, DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { parseManufacturingOverview } from "@/lib/runtime-contracts/overview";
import { useAxisQuery } from "@/lib/use-axis-query";

const DEMO_BADGE_DESCRIPTION_ID = "demo-badge-description";

export const DEMO_BADGE_OVERVIEW_ENDPOINT = `${OPERATIONS_API_PREFIX}/overview`;

/**
 * Topbar "Demo" pill (task 6.3): shown only when the tenant's overview
 * answers with a demo scenario — i.e. the demo bootstrap has run. Loading,
 * 404 (never bootstrapped), and errors all render nothing; the badge is an
 * annotation, never a state surface.
 */
export function DemoBadge({
  enabled = true,
  tenantId = DEMO_TENANT_ID,
}: {
  enabled?: boolean;
  tenantId?: string;
}) {
  const overview = useAxisQuery<ManufacturingOverview>(
    buildTenantScopedPath(DEMO_BADGE_OVERVIEW_ENDPOINT, tenantId),
    { enabled, expectedTenantId: tenantId, parse: parseManufacturingOverview },
  );

  if (!overview.data?.scenario) {
    return null;
  }

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            aria-describedby={DEMO_BADGE_DESCRIPTION_ID}
            className="status-pill signal-watch cursor-help"
            tabIndex={0}
          >
            {strings.demoBadge.label}
          </span>
        </TooltipTrigger>
        <TooltipContent>{strings.demoBadge.tooltip}</TooltipContent>
      </Tooltip>
      {/* Sibling, not a child of the pill: Radix suppresses tooltips on touch,
          so this was unreachable on phones and tablets, but nesting it inside
          the trigger would fold it into the badge's own text. */}
      <span className="sr-only" id={DEMO_BADGE_DESCRIPTION_ID}>
        {strings.demoBadge.tooltip}
      </span>
    </TooltipProvider>
  );
}
