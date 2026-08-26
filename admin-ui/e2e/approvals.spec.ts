/**
 * Smoke: the unified /approvals screen renders its role-gated queue tabs and the
 * shared status filter.
 *
 * The dev admin holds every approver role (config/treasury/user), so all three
 * tabs — Configuration / Transactions / Users — are visible. The status filter
 * row exposes Pending / Changes requested / Applied / Withdrawn / All.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

test("approvals page shows the queue tabs and status filter", async ({ page }) => {
  await page.goto("/approvals");

  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();

  // Role-gated queue tabs (rendered as pill links in the tab bar).
  await expect(page.getByRole("link", { name: "Configuration" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Transactions" })).toBeVisible();
  // "Users" also names the sidebar link, so scope to the tab bar via its href.
  await expect(
    page.locator('a[href*="tab=users"]').first(),
  ).toBeVisible();

  // Shared status filter — a segmented control of buttons whose accessible
  // names carry the live counts (e.g. "Pending473"), so match by prefix.
  const statusFilter = page.getByRole("group", { name: "Filter by status" });
  await expect(statusFilter.getByRole("button", { name: /^Pending/ })).toBeVisible();
  await expect(statusFilter.getByRole("button", { name: /^Changes req/ })).toBeVisible();
  await expect(statusFilter.getByRole("button", { name: /^Applied/ })).toBeVisible();
});
