/**
 * Playwright E2E configuration for the Sasai Wallet admin UI.
 *
 * Scope: end-to-end browser tests that drive the real Next.js app against a
 * live backend + Keycloak (see e2e/README.md for the full stack recipe). This
 * is deliberately separate from the Vitest unit/component harness
 * (vitest.config.ts): Vitest owns the ".test.ts/.test.tsx" files; Playwright
 * owns only the "e2e/ .spec.ts" files, so the two never collect each other's.
 *
 * Auth: the `setup` project (e2e/auth.setup.ts) logs in each dev admin once and
 * writes a storageState under e2e/.auth/. Every real spec depends on `setup`
 * and loads the appropriate storageState, so specs start already authenticated.
 *
 * Artefacts: screenshot + video are captured for EVERY test (pass or fail) so
 * the HTML report shows what each scenario actually looked like; traces are
 * kept only on failure to bound overhead. `npm run e2e:report` opens the
 * latest HTML report (playwright-report/); each run is also archived to
 * ../test-reports/e2e-history/<timestamp>/ by e2e/archive-report.mjs so past
 * runs stay viewable.
 */
import { defineConfig, devices } from "@playwright/test";

/** The admin UI dev server origin. Overridable for a non-local target. */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

/** Absolute paths (relative to testDir) of the two admin storageStates. */
export const STORAGE_STATE = {
  maker: "e2e/.auth/admin-test.json",
  checker: "e2e/.auth/admin-approver.json",
} as const;

export default defineConfig({
  testDir: "e2e",
  // Only Playwright spec files — never pick up Vitest `*.test.ts` sources.
  testMatch: /.*\.spec\.ts/,
  // Maker-checker specs open two sessions and share proposal state through the
  // backend, so a parallel run of the whole file set would race. Serialise.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["html", { outputFolder: "playwright-report", open: "never" }], ["list"]],
  // Failure artifacts (videos/screenshots/traces) are written DURING runs; keep
  // them OUTSIDE admin-ui so the Next dev watcher doesn't see the writes and
  // recompile mid-test (that thrash was blowing test budgets).
  outputDir: "../test-reports/e2e-artifacts",
  // Dev-mode reality: routes compile lazily and /approvals SSRs its full queues
  // (thousands of rows after load tests), so a maker-checker flow with two
  // approvals visits can be slow. Generous per-test budget; expect stays tight.
  timeout: 150_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: BASE_URL,
    // Always capture visual evidence — passing tests need review artefacts too.
    screenshot: "on",
    video: "on",
    trace: "retain-on-failure",
  },

  projects: [
    // Logs both dev admins in and persists their storageState. Every other
    // project depends on this, so it always runs first.
    { name: "setup", testMatch: /auth\.setup\.ts/ },

    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
  ],

  // Attach to an already-running `npm run dev` rather than fighting it; only
  // spawn one if nothing is listening on :3000. The dev server (and the backend
  // + Keycloak it depends on) must be up for a green run — see e2e/README.md.
  webServer: {
    command: "npm run dev",
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 180_000,
  },
});
