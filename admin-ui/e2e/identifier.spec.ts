/**
 * Direct platform-admin action (Epic 27, Stories 27.2 + 27.3) — add then
 * manually verify an account-number identifier. No maker-checker here: these
 * are single-admin operations, so this spec runs entirely in the maker context.
 *
 * 1. On Alice's user-detail page, open "Add identifier", pick "Account number",
 *    add a fresh account number → it lands UNVERIFIED, surfacing a "Verify"
 *    affordance (account numbers verify manually, not via OTP).
 * 2. Click "Verify" → the row flips to a green "Verified" badge.
 *
 * The account number carries a per-run token so re-runs never collide with the
 * identifier-uniqueness guard.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

const ALICE_PHONE = "+27825550001";
const ALICE_LOOKUP = `/users?type=phone&value=${encodeURIComponent(ALICE_PHONE)}`;

test("add an account-number identifier, then verify it", async ({ page }) => {
  const token = Date.now().toString().slice(-8);
  const accountNumber = `ZA-E2E-${token}`;

  await page.goto(ALICE_LOOKUP);
  // The user-detail sections are collapsible tabs and start closed, so the
  // identifier controls are not in the DOM until their tab is opened.
  await page.getByRole("tab", { name: "Personal & KYC" }).click();
  await expect(page.getByRole("button", { name: "Add identifier" })).toBeVisible();

  // ---- Add an unverified account-number identifier -----------------------
  await page.getByRole("button", { name: "Add identifier" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByText("Attach a phone, email, or account number"),
  ).toBeVisible();

  // Switch the type Select (Radix combobox → listbox option) to Account number.
  await dialog.getByRole("combobox").click();
  await page.getByRole("option", { name: "Account number" }).click();

  await dialog.getByLabel("Value").fill(accountNumber);
  await dialog.getByRole("button", { name: "Add identifier" }).click();

  await expect(page.getByText(/identifier added/i)).toBeVisible();

  // The new row shows the account number with a Verify affordance (unverified).
  const identRow = page.getByRole("listitem").filter({ hasText: accountNumber });
  await expect(identRow).toBeVisible();
  await expect(identRow.getByRole("button", { name: "Verify" })).toBeVisible();

  // ---- Verify it ----------------------------------------------------------
  await identRow.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText(/identifier verified/i)).toBeVisible();

  // Row now carries the green "Verified" badge and no longer offers Verify.
  const verifiedRow = page.getByRole("listitem").filter({ hasText: accountNumber });
  await expect(verifiedRow.getByText("Verified")).toBeVisible();
});
