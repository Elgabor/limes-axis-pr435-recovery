import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// The suite runs without vitest globals, so testing-library's automatic
// cleanup never registers itself; do it explicitly.
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

// jsdom lacks layout APIs that Radix popper (floating-ui) and cmdk rely on.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
