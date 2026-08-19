/**
 * Money flow: maker-checker on funding a user wallet (Epic 18).
 *
 * Admin "fund a user" is four-eyes — it DEBITs the operator cash float and
 * CREDITs a user's wallet, so it must be proposed by one admin and approved by
 * another before any ledger write.
 *
 * 1. As the MAKER (admin-test), open the /system-wallets "Fund user" dialog,
 *    target the seeded Alice (+27825550001) by phone identifier, and propose a
 *    distinct ZAR amount → "Proposed for approval" toast.
 * 2. As the CHECKER (admin-approver — different admin), approve it under
 *    Approvals → Transactions (Approve + Confirm → APPLIED).
 * 3. Assert the effect on Alice's user-detail page: her ZAR wallet available
 *    balance rose by exactly the funded amount.
 *
 * The amount is randomised and small (sub-1000, well under any wallet ceiling)
 * so the money-operation summary is individually findable and re-runs simply
 * stack more funds without colliding. The seed pre-funds the operator float, so
 * the fund can actually apply.
 */
import { test, expect, type Page } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

/** Alice, seeded in the default tenant with a single ZAR wallet (make seed). */
const ALICE_PHONE = "+27825550001";
const ALICE_LOOKUP = `/users?type=phone&value=${encodeURIComponent(ALICE_PHONE)}`;

/** A distinct sub-1000 amount ("NNN.NN") — no thousands separator to escape. */
function uniqueAmount(): string {
  const base = 100 + Math.floor(Math.random() * 800);
  const cents = String(Math.floor(Math.random() * 100)).padStart(2, "0");
  return `${base}.${cents}`;
}

/** Read Alice's ZAR financial-wallet AVAILABLE balance as a number. */
async function readAliceZarAvailable(page: Page): Promise<number> {
  await page.goto(ALICE_LOOKUP);
  // Alice holds both a ZAR and an INR financial wallet — scope to ZAR.
  const row = page
    .getByRole("row")
    .filter({ hasText: "Financial wallet" })
    .filter({ hasText: "ZAR" });
  await expect(row).toBeVisible();
  // The Available cell is the row's only font-semibold cell.
  const text = await row.locator("td.font-semibold").innerText();
  return parseFloat(text.replace(/[^0-9.]/g, ""));
}

test("maker proposes funding Alice; checker approves and her balance rises", async ({
  page,
  browser,
}) => {
  const amount = uniqueAmount();

  const balanceBefore = await readAliceZarAvailable(page);

  // ---- Maker: propose the fund -------------------------------------------
  await page.goto("/system-wallets");
  await expect(page.getByRole("heading", { name: "System wallets" })).toBeVisible();
  await page.getByRole("button", { name: "Fund user" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Fund a user wallet")).toBeVisible();
  // Identifier type defaults to Phone; the value input carries the phone
  // placeholder. Currency defaults to ZAR.
  await dialog.getByPlaceholder("+27 82 555 0001").fill(ALICE_PHONE);
  await dialog.getByLabel("Amount", { exact: true }).fill(amount);
  await dialog.getByLabel(/Reason/).fill(`E2E fund Alice ${amount}`);
  await dialog.getByRole("button", { name: "Fund user" }).click();

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

    // Summary reads "Fund Alice Mokoena with ZAR NNN.NN" — match by the unique amount.
    const opRow = checkerPage.getByRole("row").filter({ hasText: amount });
    await expect(opRow).toBeVisible();
    await opRow.getByRole("button", { name: "View" }).click();

    const drawer = checkerPage.getByRole("dialog");
    await drawer.getByRole("button", { name: "Approve" }).click();
    await drawer.getByRole("button", { name: "Confirm approve" }).click();

    await expect(checkerPage.getByText(/operation approved/i)).toBeVisible();
    // Approving revalidates + closes the drawer; the APPLIED effect is verified
    // below on Alice's balance. Confirm it also left the Pending queue.
    await checkerPage.goto("/approvals?tab=transactions&status=APPLIED");
    await expect(
      checkerPage.getByRole("row").filter({ hasText: amount }),
    ).toBeVisible();
  } finally {
    await checkerContext.close();
  }

  // ---- Effect: Alice's ZAR available balance rose by the funded amount ---
  await expect
    .poll(async () => readAliceZarAvailable(page), { timeout: 15_000 })
    .toBeGreaterThan(balanceBefore);

  const balanceAfter = await readAliceZarAvailable(page);
  expect(Math.abs(balanceAfter - (balanceBefore + Number(amount)))).toBeLessThan(0.01);
});
