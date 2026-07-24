/**
 * Smoke: an authenticated admin lands on the dashboard and sees the app shell.
 *
 * Uses the maker (admin-test) storageState written by the setup project, so the
 * test starts already signed in. Verifies the root route redirects into
 * /dashboard and the persistent sidebar (with the Approvals entry) renders.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

test("dashboard loads with the app shell", async ({ page }) => {
  await page.goto("/");
  // Root redirects to /dashboard (app/page.tsx).
  await expect(page).toHaveURL(/\/dashboard/);

  // Sidebar nav is present — a couple of stable entries prove the shell mounted.
  await expect(page.getByRole("link", { name: "Approvals" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Users" })).toBeVisible();
});
