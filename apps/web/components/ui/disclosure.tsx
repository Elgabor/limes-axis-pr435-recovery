import type { ReactNode } from "react";

/** Native disclosure keeps advanced controls keyboard accessible and drafts mounted. */
export function Disclosure({ title, children }: {
  title: string;
  children: ReactNode;
}) {
  return (
    <details className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10">
      <summary className="min-h-6 cursor-pointer text-sm font-medium text-ink">{title}</summary>
      <div className="mt-4 grid min-w-0 gap-3">{children}</div>
    </details>
  );
}
