"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  fetchTenantVocabulary,
  type TenantVocabularySet,
} from "@/lib/platform-tenants";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

export type TenantVocabularySource = "loading" | "api" | "unavailable" | "missing";

type TenantVocabularyContextValue = {
  tenantId: string | null;
  vocabularySet: TenantVocabularySet | null;
  source: TenantVocabularySource;
  labelDomain: (domain: string) => string;
  replaceVocabulary: (record: TenantVocabularySet) => void;
};

const fallbackContext: TenantVocabularyContextValue = {
  tenantId: null,
  vocabularySet: null,
  source: "loading",
  labelDomain: (domain) => domain,
  replaceVocabulary: () => undefined,
};

const TenantVocabularyContext =
  createContext<TenantVocabularyContextValue>(fallbackContext);

export function resolveVocabularyTenantId(
  pathname: string,
  consoleTenantId: string | null,
): string | null {
  const segments = pathname.split("/").filter(Boolean);

  if (segments[0] !== "tenants") {
    return consoleTenantId;
  }

  if (!segments[1]) {
    return null;
  }

  try {
    return decodeURIComponent(segments[1]);
  } catch {
    return null;
  }
}

export function TenantVocabularyProvider({
  children,
  enabled,
  tenantId,
}: {
  children: ReactNode;
  enabled: boolean;
  tenantId: string | null;
}) {
  const { refreshNonce } = useConsole();
  const { session } = useOidcConsoleSession();
  const [loadState, setLoadState] = useState<{
    tenantId: string;
    vocabularySet: TenantVocabularySet | null;
    source: TenantVocabularySource;
  } | null>(null);
  const replacementVersionRef = useRef(0);

  useEffect(() => {
    if (!enabled || !tenantId) {
      return;
    }

    const controller = new AbortController();
    const requestedTenantId = tenantId;
    const requestedVersion = replacementVersionRef.current;

    async function loadVocabulary() {
      try {
        const result = await fetchTenantVocabulary(requestedTenantId, {
          session,
          signal: controller.signal,
        });

        if (
          controller.signal.aborted
          || requestedVersion !== replacementVersionRef.current
        ) {
          return;
        }

        if (result === null) {
          setLoadState({
            tenantId: requestedTenantId,
            vocabularySet: null,
            source: "missing",
          });
          return;
        }

        if (result.tenant_id !== requestedTenantId) {
          setLoadState({
            tenantId: requestedTenantId,
            vocabularySet: null,
            source: "unavailable",
          });
          return;
        }

        setLoadState({
          tenantId: requestedTenantId,
          vocabularySet: result,
          source: "api",
        });
      } catch {
        if (
          !controller.signal.aborted
          && requestedVersion === replacementVersionRef.current
        ) {
          setLoadState({
            tenantId: requestedTenantId,
            vocabularySet: null,
            source: "unavailable",
          });
        }
      }
    }

    void loadVocabulary();

    return () => controller.abort();
  }, [enabled, refreshNonce, session, tenantId]);

  const currentState =
    enabled && tenantId && loadState?.tenantId === tenantId
      ? loadState
      : null;
  const vocabularySet = currentState?.vocabularySet ?? null;
  const source = currentState?.source ?? "loading";

  const labelDomain = useCallback(
    (domain: string) => {
      const configuredLabel = vocabularySet?.vocabulary.domain_labels[domain]?.trim();
      return configuredLabel || domain;
    },
    [vocabularySet],
  );

  const replaceVocabulary = useCallback((record: TenantVocabularySet) => {
    if (record.tenant_id === tenantId) {
      replacementVersionRef.current += 1;
      setLoadState({
        tenantId: record.tenant_id,
        vocabularySet: record,
        source: "api",
      });
    }
  }, [tenantId]);

  const value = useMemo(
    () => ({
      tenantId,
      vocabularySet,
      source,
      labelDomain,
      replaceVocabulary,
    }),
    [labelDomain, replaceVocabulary, source, tenantId, vocabularySet],
  );

  return (
    <TenantVocabularyContext.Provider value={value}>
      {children}
    </TenantVocabularyContext.Provider>
  );
}

export function useTenantVocabulary(): TenantVocabularyContextValue {
  return useContext(TenantVocabularyContext);
}
