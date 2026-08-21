import { defineConfig } from "vitest/config";
import path from "node:path";

const alias = {
  "@": path.resolve(import.meta.dirname),
};

export default defineConfig({
  test: {
    // jsdom suites are interaction-heavy; bounding concurrency keeps their
    // per-test budget stable on both developer laptops and CI.
    maxWorkers: 4,
    projects: [
      {
        resolve: { alias },
        test: {
          name: "node",
          environment: "node",
          include: ["**/*.test.ts"],
        },
      },
      {
        resolve: { alias },
        test: {
          name: "jsdom",
          environment: "jsdom",
          include: ["**/*.test.tsx"],
          setupFiles: ["./vitest.setup.ts"],
          // A userEvent-driven test spends most of its budget in jsdom and
          // React commits rather than in assertions, so the 5s default is a
          // load-tolerance ceiling, not a statement about how long these
          // should take. Under contention it produced timeout failures across
          // a dozen unrelated tests that pass deterministically when given
          // room. Still short enough that a genuine hang fails fast.
          testTimeout: 15_000,
        },
      },
    ],
  },
});
