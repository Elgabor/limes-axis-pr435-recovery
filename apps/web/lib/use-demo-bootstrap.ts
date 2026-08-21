"use client";

import { useState } from "react";

import { useToast } from "@/components/ui/toast";
import {
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import { formatContextPath } from "@/lib/format";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { strings } from "@/lib/strings";
import { parseDemoBootstrapResult } from "@/lib/runtime-contracts/bootstrap";
import { parseIdentitySessionReadModel } from "@/lib/runtime-contracts/overview";
import { DEMO_TENANT_ID } from "@/lib/tenant-scope";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

/*
 * Demo switch (spec §6, task 6.3): one POST provisions the manufacturing demo
 * scenario into the console tenant. The endpoint is idempotent — a replay
 * answers 200 with `idempotent_replay: true` — so the CTA is safe to retry.
 */

export const DEMO_BOOTSTRAP_ENDPOINT = "/demo/manufacturing/bootstrap";
export const DEMO_BOOTSTRAP_SCOPE = "demo:scenario:bootstrap";
export { DEMO_TENANT_ID } from "@/lib/tenant-scope";
/** Fallback actor when no authenticated API session is attached. */
export const DEMO_CONSOLE_ACTOR = "demo-console-operator";

export type DemoBootstrapRequestPayload = {
  tenant_id: string;
  requested_by: string;
  actor_scopes: string[];
};

export type DemoBootstrapSurface = {
  surface: string;
  reference_id: string;
  state: "created" | "existing";
};

export type DemoBootstrapResult = {
  tenant_id: string;
  scenario: string | null;
  plant_name: string | null;
  bootstrapped: boolean;
  surfaces: DemoBootstrapSurface[];
  audit_event_id: string;
  idempotent_replay: boolean;
};

export function buildDemoBootstrapPayload(actorId: string): DemoBootstrapRequestPayload {
  return {
    tenant_id: DEMO_TENANT_ID,
    requested_by: actorId,
    actor_scopes: [DEMO_BOOTSTRAP_SCOPE],
  };
}

/**
 * Bootstrap the demo scenario from the onboarding checklist CTA: POST the
 * scope-gated request, toast on success, then refresh the console so the
 * overview refetches and the control room replaces the checklist. Failures
 * land in `error` for inline rendering on the checklist.
 */
export function useDemoBootstrap() {
  const { triggerRefresh } = useConsole();
  const { push } = useToast();
  const { session } = useOidcConsoleSession();
  const { data: identitySession } = useAxisQuery<IdentitySessionReadModel>("/identity/session", {
    parse: parseIdentitySessionReadModel,
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<AxisOperatorError | null>(null);

  async function bootstrapDemo() {
    if (pending) {
      return;
    }
    setPending(true);
    setError(null);

    try {
      const result = await axisFetchParsedJson<DemoBootstrapResult>(
        DEMO_BOOTSTRAP_ENDPOINT,
        parseDemoBootstrapResult,
        {
          method: "POST",
          session,
          body: buildDemoBootstrapPayload(identitySession?.actor_id ?? DEMO_CONSOLE_ACTOR),
        },
      );
      push({
        title: strings.onboarding.exploreDemo.toastTitle,
        detail: formatContextPath(result.scenario, result.plant_name),
        tone: "positive",
      });
      triggerRefresh();
    } catch (caught) {
      setError(toAxisOperatorError(caught, strings.onboarding.exploreDemo.errorFallback));
    } finally {
      setPending(false);
    }
  }

  return { bootstrapDemo, pending, error };
}
