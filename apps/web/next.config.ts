import type { NextConfig } from "next";
import path from "node:path";

/**
 * Baseline security headers for the console.
 *
 * This app renders tenant governance data, audit evidence and policy
 * definitions, and exposes one-click destructive controls (tenant suspend,
 * session revoke). Without `frame-ancestors`/`X-Frame-Options` the whole
 * console is clickjackable; without `Referrer-Policy`, tenant and policy ids
 * leak in the `Referer` header of every outbound link.
 *
 * Deliberately absent: `Content-Security-Policy`. The theme bootstrap is an
 * inline script and Next emits per-build inline flight payloads, so a
 * maintainable CSP needs a nonce issued from middleware — a separate change.
 */
export const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "X-Robots-Tag", value: "noindex, nofollow" },
] as const;

const nextConfig: NextConfig = {
  // The default bottom-left placement sits on top of the sidebar's account row.
  devIndicators: { position: "bottom-right" },
  allowedDevOrigins: ["127.0.0.1"],
  reactStrictMode: true,
  turbopack: {
    root: path.resolve(process.cwd(), "../.."),
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders.map(({ key, value }) => ({ key, value })),
      },
    ];
  },
};

export default nextConfig;
