"use client";

import { strings } from "@/lib/strings";

import "./globals.css";

/**
 * Last-resort boundary for a throw in the root layout itself, where `AppShell`
 * and the theme bootstrap are unavailable — hence its own document and inline
 * neutral styling rather than the token layer, which may not have applied.
 */
export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          padding: "2rem",
          background: "#f7f8fb",
          color: "#04122e",
          fontFamily: "ui-sans-serif, system-ui, -apple-system, sans-serif",
        }}
      >
        <main style={{ maxWidth: "32rem", textAlign: "center" }}>
          <h1 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 600 }}>
            {strings.globalError.title}
          </h1>
          <p style={{ margin: "0.5rem 0 0", fontSize: "0.875rem", color: "#6e7a94" }}>
            {strings.globalError.detail}
          </p>
          {error.digest ? (
            <p
              style={{
                margin: "1rem 0 0",
                fontFamily: "ui-monospace, SFMono-Regular, monospace",
                fontSize: "0.75rem",
                color: "#6e7a94",
              }}
            >
              {strings.states.reference}: {error.digest}
            </p>
          ) : null}
          {/* Deliberately a plain anchor: the root layout has failed, so the
              router cannot be trusted. A full document load is the recovery. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              marginTop: "1.5rem",
              padding: "0 0.875rem",
              height: "2.25rem",
              borderRadius: "0.5rem",
              background: "#04122e",
              color: "#fff",
              fontSize: "0.875rem",
              fontWeight: 500,
              textDecoration: "none",
            }}
          >
            {strings.globalError.action}
          </a>
        </main>
      </body>
    </html>
  );
}
