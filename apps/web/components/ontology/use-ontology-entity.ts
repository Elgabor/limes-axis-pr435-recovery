"use client";

import { useEffect, useState } from "react";

import {
  axisFetchParsedJson,
  toAxisOperatorError,
} from "@/lib/axis-api";
import type { ManufacturingOntologyEntityDetail } from "@/lib/ontology-demo";
import { parseManufacturingOntologyEntityDetail } from "@/lib/runtime-contracts/ontology";
import { buildTenantScopedPath, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

export type OntologyEntitySource = "loading" | "api" | "unavailable" | "missing";

type OntologyEntityResult = {
  queryKey: string;
  detail: ManufacturingOntologyEntityDetail | null;
  errorRequestId: string | null;
  source: OntologyEntitySource;
};

export function buildOntologyEntityPath(nodeId: string, tenantId: string): string {
  return buildTenantScopedPath(
    `${OPERATIONS_API_PREFIX}/ontology/entities/${encodeURIComponent(nodeId)}`,
    tenantId,
  );
}

/**
 * Fetch a single ontology entity detail from the Axis API. Shared by the
 * full entity page and the explorer slide-over; passing `null` keeps the
 * hook idle (nothing is fetched while the slide-over is closed).
 *
 * The result is keyed by the tenant-scoped request path, so switching either
 * tenant or entity reports "loading" instead of exposing the previous scope.
 */
export function useOntologyEntity(
  nodeId: string | null,
  tenantId: string,
  enabled = true,
) {
  const [result, setResult] = useState<OntologyEntityResult | null>(null);
  const { session } = useOidcConsoleSession();
  const { refreshNonce } = useConsole();
  const entityPath = nodeId ? buildOntologyEntityPath(nodeId, tenantId) : null;

  useEffect(() => {
    const queryKey = entityPath;
    if (!nodeId || !queryKey || !enabled) {
      return;
    }
    const requestedPath: string = queryKey;

    const controller = new AbortController();

    async function fetchEntity() {
      try {
        const detail = await axisFetchParsedJson(
          requestedPath,
          (value) => {
            const parsed = parseManufacturingOntologyEntityDetail(value);
            if (parsed.tenant_id !== tenantId) {
              throw new Error(`Ontology entity tenant does not match ${tenantId}.`);
            }
            return parsed;
          },
          {
            session,
            signal: controller.signal,
          },
        );
        setResult({
          queryKey: requestedPath,
          detail,
          errorRequestId: null,
          source: "api",
        });
      } catch (caught) {
        if (!controller.signal.aborted) {
          const failure = toAxisOperatorError(
            caught,
            "Axis could not load this ontology entity.",
          );
          if (failure.status === 404) {
            setResult({
              queryKey: requestedPath,
              detail: null,
              errorRequestId: null,
              source: "missing",
            });
            return;
          }
          setResult((current) => ({
            queryKey: requestedPath,
            detail: current?.queryKey === requestedPath ? current.detail : null,
            errorRequestId: failure.requestId,
            source: "unavailable",
          }));
        }
      }
    }

    void fetchEntity();

    return () => controller.abort();
  }, [enabled, entityPath, nodeId, refreshNonce, session, tenantId]);

  if (!nodeId || !entityPath || !enabled || result?.queryKey !== entityPath) {
    return {
      detail: null,
      endpoint: entityPath,
      errorRequestId: null,
      source: "loading" as const,
    };
  }

  return {
    detail: result.detail,
    endpoint: entityPath,
    errorRequestId: result.errorRequestId,
    source: result.source,
  };
}
