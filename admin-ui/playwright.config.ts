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
 * Failure artefacts: screenshot + video + trace are captured only on failure
 * and land under test-results/. `npx playwright show-report` opens the HTML
 * report (playwright-report/) with the trace viewer.
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
  outputDir: "test-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: BASE_URL,
    screenshot: "only-on-failure",
    video: "retain-on-failure",
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
