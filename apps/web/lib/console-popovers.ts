"use client";

import { useEffect } from "react";

/**
 * The console's popovers used to be siblings in the topbar, so a single
 * `activePanel` state made them mutually exclusive. Identity moved to the
 * sidebar footer and owns its own state, so exclusivity now needs an explicit
 * signal: whoever opens a panel announces it, and every other host closes.
 */
const POPOVER_OPENED_EVENT = "axis:console-popover-opened";

export function announcePopoverOpened(sourceId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(POPOVER_OPENED_EVENT, { detail: sourceId }));
}

/** Closes this host's panel whenever a different host opens one. */
export function useExclusivePopover(sourceId: string, close: () => void): void {
  useEffect(() => {
    function onOpened(event: Event) {
      if ((event as CustomEvent<string>).detail !== sourceId) {
        close();
      }
    }

    window.addEventListener(POPOVER_OPENED_EVENT, onOpened);
    return () => window.removeEventListener(POPOVER_OPENED_EVENT, onOpened);
  }, [close, sourceId]);
}
