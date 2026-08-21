import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";

describe("Next.js demo configuration", () => {
  it("allows the in-app Browser 127.0.0.1 origin during local demo development", () => {
    expect(nextConfig.allowedDevOrigins).toContain("127.0.0.1");
  });
});

describe("security headers", () => {
  async function headersFor(path: string): Promise<Record<string, string>> {
    const rules = (await nextConfig.headers?.()) ?? [];
    const matching = rules.filter((rule) => new RegExp(`^${rule.source.replace("/:path*", "")}`).test(path));
    return Object.fromEntries(
      matching.flatMap((rule) => rule.headers.map((header) => [header.key, header.value])),
    );
  }

  it.each([
    ["Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"],
    ["X-Frame-Options", "DENY"],
    ["X-Content-Type-Options", "nosniff"],
    ["Referrer-Policy", "strict-origin-when-cross-origin"],
    ["Permissions-Policy", "camera=(), microphone=(), geolocation=()"],
    ["X-Robots-Tag", "noindex, nofollow"],
  ])("sets %s on every route", async (key, value) => {
    expect(await headersFor("/audit")).toMatchObject({ [key]: value });
  });

  it("applies the headers to the root route as well as nested routes", async () => {
    // `/:path*` must match "/" too, or the overview ships unprotected.
    expect(Object.keys(await headersFor("/"))).toContain("X-Frame-Options");
  });

  it("does not ship a Content-Security-Policy without a nonce strategy", async () => {
    // A CSP here would need hashes for Next's per-build inline scripts and
    // would silently rot. Tracked as separate middleware work; asserted so it
    // is a deliberate decision rather than an oversight.
    expect(await headersFor("/audit")).not.toHaveProperty("Content-Security-Policy");
  });
});
