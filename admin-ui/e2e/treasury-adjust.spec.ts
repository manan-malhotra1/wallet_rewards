/**
 * HEADLINE money flow: maker-checker on a system-wallet adjustment.
 *
 * The single most sensitive treasury move — topping up the operator cash float
 * from the bank — must never execute on one admin's say-so. This exercises the
 * full four-eyes path end to end against the live stack:
 *
 * 1. As the MAKER (admin-test), on /system-wallets open the ZAR "Cash float"
 *    (system_cash_inflow) Adjust dialog, FUND it by a distinct magnitude with
 *    the seeded "Primary" bank mirror as the counter-leg, and Propose. This
 *    maps to `adjust_system_wallet` (CREDIT float / DEBIT the bank mirror). A
 *    "Proposed for approval" toast confirms it entered the money maker-checker
 *    pipeline (Epic 18) rather than moving money directly.
 * 2. As the CHECKER (admin-approver — a DIFFERENT admin, so self-approval is
 *    not in play), find that proposal under Approvals → Transactions by its
 *    unique amount, Approve + Confirm, and assert it reaches APPLIED (the dev
 *    default is 1 required approval, so one checker applies it).
 * 3. Assert the effect: the float balance on /system-wallets rose by the
 *    adjusted amount.
 *
 * A random sub-1000 magnitude keeps each run's proposal individually findable
 * (no thousands separator to escape) and additive, so re-runs never collide.
 *
 * Requires the seeded ZAR cash float + "Primary" bank mirror (scripts/seed.py).
 */
import { test, expect, type Page } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

/** A distinct sub-1000 magnitude ("457.NN") so the summary text is unambiguous. */
function uniqueMagnitude(): { typed: string; shown: string } {
  const base = 100 + Math.floor(Math.random() * 800); // 100..899
  const cents = String(Math.floor(Math.random() * 100)).padStart(2, "0");
  return { typed: `${base}.${cents}`, shown: `${base}.${cents}` };
}

/** Read the ZAR "Cash float" balance from the System wallets table as a number. */
async function readFloatBalance(page: Page): Promise<number> {
  await page.goto("/system-wallets");
  // There is a Cash float per currency (INR + ZAR) — scope to the ZAR one.
  const row = page
    .getByRole("row")
    .filter({ hasText: "Cash float" })
    .filter({ hasText: "ZAR" });
  await expect(row).toBeVisible();
  // First right-aligned cell is Balance (Actions is also right-aligned).
  const text = await row.locator("td.text-right").first().innerText();
  return parseFloat(text.replace(/[^0-9.]/g, ""));
}

test("maker proposes a cash-float top-up; checker approves and the float rises", async ({
  page,
  browser,
}) => {
  const amount = uniqueMagnitude();

  const balanceBefore = await readFloatBalance(page);

  // ---- Maker: propose the adjustment -------------------------------------
  await page.goto("/system-wallets");
  await expect(page.getByRole("heading", { name: "System wallets" })).toBeVisible();

  const floatRow = page
    .getByRole("row")
    .filter({ hasText: "Cash float" })
    .filter({ hasText: "ZAR" });
  await floatRow.getByRole("button", { name: "Adjust" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Adjust system wallet")).toBeVisible();
  // "Fund" is the default direction — leave it. Fill amount + reason.
  await dialog.getByLabel(/Amount/).fill(amount.typed);

  // Bank-mirror counter-leg is a Radix Select (role combobox → listbox options).
  await dialog.getByRole("combobox").click();
  await page.getByRole("option", { name: "Primary" }).click();

  await dialog.getByLabel(/Reason/).fill(`E2E float top-up ${amount.typed}`);
  await dialog.getByRole("button", { name: "Fund wallet" }).click();

  await expect(page.getByText(/proposed for approval/i)).toBeVisible();

  // ---- Checker: approve under Transactions -------------------------------
  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    // Status values are the UPPERCASE StatusKeys (lib/approvals-filter.ts);
    // anything else silently falls back to the default PENDING filter.
    await checkerPage.goto("/approvals?tab=transactions&status=PENDING");
    await expect(
      checkerPage.getByRole("heading", { name: "Approvals" }),
    ).toBeVisible();

    // Locate this proposal by its unique magnitude (summary: "Add 457.NN to
    // Cash float via Primary"), then open its detail drawer.
    const opRow = checkerPage.getByRole("row").filter({ hasText: amount.shown });
    await expect(opRow).toBeVisible();
    await opRow.getByRole("button", { name: "View" }).click();

    const drawer = checkerPage.getByRole("dialog");
    await drawer.getByRole("button", { name: "Approve" }).click();
    await drawer.getByRole("button", { name: "Confirm approve" }).click();

    await expect(checkerPage.getByText(/operation approved/i)).toBeVisible();

    // Approving revalidates the queue (the applied op drops off the Pending
    // filter and the drawer unmounts), so confirm APPLIED under the Applied
    // filter rather than in the now-closed drawer.
    await checkerPage.goto("/approvals?tab=transactions&status=APPLIED");
    await expect(
      checkerPage.getByRole("row").filter({ hasText: amount.shown }),
    ).toBeVisible();
  } finally {
    await checkerContext.close();
  }

  // ---- Effect: the float balance rose by the adjusted amount -------------
  await expect
    .poll(async () => readFloatBalance(page), { timeout: 15_000 })
    .toBeGreaterThan(balanceBefore);

  const balanceAfter = await readFloatBalance(page);
  expect(Math.abs(balanceAfter - (balanceBefore + Number(amount.typed)))).toBeLessThan(
    0.01,
  );
});
