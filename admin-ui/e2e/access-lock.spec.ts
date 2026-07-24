/**
 * Smoke: admin access-lock on a seeded user.
 *
 * Looks up Alice (+27825550001 — seeded by scripts/seed.py) on /users, imposes a
 * login lock through its confirm dialog, asserts the "Login locked" pill
 * appears, then Restores access and asserts it clears.
 *
 * This exercises the <AccessLockControl> hero action + <AccessLevelPill>, and
 * is distinct from the automatic PIN-lockout badge. Selectors are a best-guess
 * from the components and may need tuning on the first live run.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

/** Alice, seeded in the default tenant (make seed). */
const ALICE_PHONE = "+27825550001";

test("lock then restore a user's login access", async ({ page }) => {
  await page.goto("/users");

  // Identifier type defaults to Phone; just fill the value and look up.
  await page.getByLabel("Value").fill(ALICE_PHONE);
  await page.getByRole("button", { name: "Lookup" }).click();

  // Detail card renders once the identifier resolves.
  await expect(page.getByRole("button", { name: "Lock login" })).toBeVisible();

  // ---- Lock login ----------------------------------------------------------
  await page.getByRole("button", { name: "Lock login" }).click();
  const lockDialog = page.getByRole("dialog");
  await expect(
    lockDialog.getByText("Lock login for this user?"),
  ).toBeVisible();
  // Confirm inside the dialog (a second "Lock login" button).
  await lockDialog.getByRole("button", { name: "Lock login" }).click();

  await expect(page.getByText("Login locked")).toBeVisible();

  // ---- Restore access ------------------------------------------------------
  await page.getByRole("button", { name: "Restore access" }).click();
  const restoreDialog = page.getByRole("dialog");
  await expect(
    restoreDialog.getByText("Restore access for this user?"),
  ).toBeVisible();
  await restoreDialog.getByRole("button", { name: "Restore access" }).click();

  // The "Login locked" pill clears once access is active again.
  await expect(page.getByText("Login locked")).toHaveCount(0);
});
