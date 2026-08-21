import { describe, expect, it } from "vitest";

import {
  deriveSourceState,
  PROVENANCE_NOT_APPLICABLE,
} from "./source-state";

describe("deriveSourceState", () => {
  it("uses payload provenance after a successful API response", () => {
    expect(deriveSourceState("api", true, "live")).toBe("live");
    expect(deriveSourceState("api", true, "reference_scenario")).toBe("reference");
    expect(deriveSourceState("api", true, "empty")).toBe("empty");
  });

  it("never describes reference-scenario data as live", () => {
    expect(deriveSourceState("api", true, "reference_scenario")).not.toBe("live");
  });

  it("lets a failed refresh override the cached payload provenance", () => {
    expect(deriveSourceState("unavailable", true, "reference_scenario")).toBe("stale");
    expect(deriveSourceState("tenant_not_found", true, "live")).toBe("stale");
    expect(deriveSourceState("unavailable", true, "empty")).toBe("stale");
  });

  it("keeps a successful empty payload distinct from an unavailable request", () => {
    expect(deriveSourceState("api", true, "empty")).toBe("empty");
    expect(deriveSourceState("unavailable", false, "empty")).toBe("unavailable");
  });

  it("treats success from an explicitly provenance-less endpoint as live", () => {
    expect(deriveSourceState("api", true, PROVENANCE_NOT_APPLICABLE)).toBe("live");
  });

  it("never relabels a successful payload with accidentally missing provenance as live", () => {
    expect(() => deriveSourceState("api", true, undefined)).toThrow(
      "Successful source data requires explicit provenance",
    );
    expect(deriveSourceState("api", false)).toBe("unavailable");
  });

  it("preserves loading before any provenance-less response arrives", () => {
    expect(deriveSourceState("loading", false)).toBe("loading");
  });
});
