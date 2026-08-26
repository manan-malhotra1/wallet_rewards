/**
 * Auth setup project — signs each dev admin in ONCE and persists their session
 * to a storageState file the real specs reuse. Runs before every other project
 * (declared as their `dependencies` in playwright.config.ts).
 *
 * The admin UI does NOT redirect to Keycloak's hosted login page — it renders
 * its own credentials form at /login (see app/login/login-form.tsx), and the
 * Keycloak password grant runs server-side inside next-auth's `authorize()`
 * callback. So "authenticating" here means filling that in-app email+password
 * form and waiting for the post-login redirect back into the app shell.
 *
 * Two admins are provisioned because maker-checker forbids self-approval: a
 * proposal by `admin-test` must be approved by a DIFFERENT admin
 * (`admin-approver`). Both hold platform-admin + config/treasury/user-approver
 * (see scripts/bootstrap_keycloak.py). Each gets its own storageState.
 */
import { test as setup, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

/**
 * Dev-seeded admins. Keycloak resolves the login form's "email" field against
 * either username or email; bootstrap_keycloak.py seeds each admin with email
 * `<username>@example.test`, so we log in with the email. The password is the
 * shared dev constant `DEV_ADMIN_PASSWORD` ("admin-test-pass"), overridable via
 * E2E_ADMIN_PASSWORD so no real secret is ever hardcoded beyond the dev default.
 */
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "admin-test-pass";

/**
 * The tenant every spec's seed data lives in (scripts/seed.py). The backend
 * lists tenants NEWEST-first and a fresh session has no tenant cookie, so a
 * dev DB with extra tenants would otherwise default to the wrong (empty) one
 * and every tenant-scoped spec would fail on missing data.
 */
const TENANT = process.env.E2E_TENANT_NAME ?? "Sasai-ZA";

const ADMINS = [
  { email: "admin-test@example.test", storageState: STORAGE_STATE.maker },
  { email: "admin-approver@example.test", storageState: STORAGE_STATE.checker },
] as const;

for (const admin of ADMINS) {
  setup(`authenticate ${admin.email}`, async ({ page }) => {
    // Hitting a protected route bounces to /login?from=… via middleware.
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);

    await page.getByLabel("Email").fill(admin.email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();

    // The server action redirects back to the originally-requested page
    // (/dashboard). Wait for the shell — the persistent "Approvals" nav link
    // only renders once authenticated inside AuthenticatedLayout. The first
    // login of a run pays the dev-server compile + Keycloak warm-up cost, so
    // this assertion gets a longer leash than the default expect timeout.
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
    await expect(
      page.getByRole("link", { name: "Approvals" }),
    ).toBeVisible();

    // Pin the active tenant to the seeded dev tenant so its cookie persists
    // into the storageState (see TENANT above for why the default is wrong).
    const switcher = page.getByRole("button", { name: "Switch tenant" });
    await expect(switcher).toBeVisible();
    if (!(await switcher.innerText()).includes(TENANT)) {
      await switcher.click();
      await page.getByRole("button", { name: TENANT }).click();
      await expect(switcher).toContainText(TENANT);
    }

    await page.context().storageState({ path: admin.storageState });
  });
}
