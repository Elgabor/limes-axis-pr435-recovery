import { describe, expect, it } from "vitest";

import {
  missingRequiredScopePermission,
} from "./scope-denial";

const baseQuery = {
  errorStatus: 403 as number | null,
  errorCode: "PERMISSION_DENIED" as string | null,
  errorReason: "missing_required_scope" as string | null,
  errorRequiredPermission: "audit:read" as string | null,
};

describe("missingRequiredScopePermission", () => {
  it("classifies an exact missing-scope denial and returns the named permission", () => {
    expect(missingRequiredScopePermission(baseQuery)).toBe("audit:read");
  });

  it.each([
    { ...baseQuery, errorStatus: 500 },
    { ...baseQuery, errorStatus: null },
    { ...baseQuery, errorCode: "TENANT_NOT_FOUND" },
    { ...baseQuery, errorReason: "tenant_mismatch" },
    { ...baseQuery, errorReason: "missing_relationship_scope:platform:x" },
    { ...baseQuery, errorRequiredPermission: null },
  ])("refuses to guess when the denial is not exact (%#)", (query) => {
    expect(missingRequiredScopePermission(query)).toBeNull();
  });
});
