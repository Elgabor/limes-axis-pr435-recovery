"use client";

import { Suspense, type ReactNode } from "react";

import { ConsoleTopbar } from "@/components/console-topbar";
import { PageHeader } from "@/components/ui/page-header";
import { LoadingPanel } from "@/components/ui/states";
import { ConsoleUrlStateProvider } from "@/lib/console-url-state";
import { strings, type PageKey } from "@/lib/strings";

type ConsolePageProps = {
  /** Route key into `strings.pages`; supplies eyebrow/title/description. */
  pageKey?: PageKey;
  /** Explicit overrides for dynamic detail routes (ontology/tenant/policy detail). */
  title?: string;
  subtitle?: string;
  eyebrow?: string;
  sourceLabel?: string;
  controls?: ReactNode;
  children: ReactNode;
};

/**
 * Page scaffold: topbar + the single PageHeader (fed from `strings.pages`
 * via `pageKey`, with explicit prop overrides for dynamic detail routes).
 */
export function ConsolePage({
  pageKey,
  title,
  subtitle,
  eyebrow,
  sourceLabel,
  controls,
  children,
}: ConsolePageProps) {
  const pageStrings = pageKey ? strings.pages[pageKey] : undefined;
  const resolvedTitle = title ?? pageStrings?.title ?? "";
  const resolvedEyebrow = eyebrow ?? pageStrings?.eyebrow ?? "";
  const resolvedDescription = subtitle ?? pageStrings?.description;

  return (
    <div className="ops-console grid min-h-screen content-start gap-3 px-4 pb-5 sm:px-6">
      <ConsoleTopbar sourceLabel={sourceLabel} />
      <PageHeader
        actions={controls}
        description={resolvedDescription}
        eyebrow={resolvedEyebrow}
        title={resolvedTitle}
      />
      <div className="grid min-w-0 gap-3.5">
        <Suspense fallback={<LoadingPanel layout="detail" />}>
          <ConsoleUrlStateProvider>{children}</ConsoleUrlStateProvider>
        </Suspense>
      </div>
    </div>
  );
}
