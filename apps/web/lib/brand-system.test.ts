import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("Axis brand system", () => {
  const globalsCss = readFileSync(join(process.cwd(), "app", "globals.css"), "utf8").toLowerCase();

  it("defines the brand palette as light-first channel tokens", () => {
    expect(globalsCss).toContain("color-scheme: light");
    expect(globalsCss).toContain("--signal: 47 100 255;");
    expect(globalsCss).toContain("--navy: 4 18 46;");
    expect(globalsCss).toContain("--cloud: 247 248 251;");
    expect(globalsCss).toContain("--mist: 217 222 232;");
    expect(globalsCss).toContain("--slate: 110 122 148;");
    expect(globalsCss).toContain("--tint-50: #f3f6ff;");
    expect(globalsCss).toContain("--tint-100: #eef3ff;");
    expect(globalsCss).toContain("--tint-200: #dce6ff;");
  });

  it("ships a navy dark theme, not a black one", () => {
    const darkBlock = globalsCss.match(/\[data-theme="dark"\]\s*\{[^}]+\}/);
    expect(darkBlock).not.toBeNull();
    expect(darkBlock?.[0]).toContain("color-scheme: dark");
    expect(darkBlock?.[0]).toContain("--bg: 4 18 46;");
    expect(darkBlock?.[0]).toContain("--surface: 9 26 58;");
    expect(darkBlock?.[0]).toContain("--ink: 237 241 248;");
    expect(darkBlock?.[0]).toContain("--line: 34 52 88;");
    expect(darkBlock?.[0]).toContain("--muted: 158 172 200;");
  });

  it("respects reduced-motion preferences", () => {
    expect(globalsCss).toContain("@media (prefers-reduced-motion: reduce)");
  });

});
