import type { Metadata } from "next";

import { ConsolePage } from "@/components/console-page";
import { EmptyPanel } from "@/components/ui/states";
import { strings } from "@/lib/strings";

export const metadata: Metadata = {
  title: strings.notFound.title,
};

/**
 * Replaces Next's built-in 404.
 *
 * The built-in renders a bare "404" *inside* the AppShell and injects an
 * unlayered `body { color:#000; background:#fff }` rule keyed to
 * `prefers-color-scheme`. This console themes off `[data-theme]` on <html>, so
 * the two disagreed: app-dark on an OS-light machine produced black text on the
 * navy background, and app-light on an OS-dark machine produced a black page
 * under a white sidebar. Defining this file removes that stylesheet entirely.
 */
export default function NotFound() {
  return (
    <ConsolePage
      eyebrow={strings.notFound.eyebrow}
      subtitle={strings.notFound.subtitle}
      title={strings.notFound.title}
    >
      {/* No `icon` prop: this is a server component and `EmptyPanel` is a
          client component, so a component-valued prop cannot cross the
          boundary — React rejects it as a non-plain object. */}
      <EmptyPanel
        action={{ href: "/", label: strings.notFound.action }}
        detail={strings.notFound.detail}
        title={strings.notFound.panelTitle}
      />
    </ConsolePage>
  );
}
