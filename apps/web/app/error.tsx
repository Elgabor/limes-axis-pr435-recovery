"use client";

import { ConsolePage } from "@/components/console-page";
import { ErrorPanel } from "@/components/ui/states";
import { strings } from "@/lib/strings";

/**
 * Route-segment error boundary.
 *
 * Without one, any render throw escalates to Next's built-in handler, which
 * renders its own document — the operator loses the sidebar, the navigation and
 * the theme, and the only way out is a browser reload. Because this boundary
 * sits under the root layout, `AppShell` stays mounted and the rest of the
 * console remains usable while one route recovers.
 */
export default function ConsoleRouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <ConsolePage
      eyebrow={strings.routeError.eyebrow}
      subtitle={strings.routeError.subtitle}
      title={strings.routeError.title}
    >
      <ErrorPanel
        detail={strings.routeError.detail}
        // In production React redacts the message to a digest; it is the only
        // thing an operator can quote to support, so surface it.
        reference={error.digest}
        title={strings.routeError.panelTitle}
        onRetry={reset}
      />
    </ConsolePage>
  );
}
