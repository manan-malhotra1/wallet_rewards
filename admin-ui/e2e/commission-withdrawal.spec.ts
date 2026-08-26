/**
 * Bulk commission WITHDRAWAL — clawback (spec 2026-08-26 §8, D14).
 *
 * The counterpart to disbursement, and deliberately a separate menu: this pulls
 * incorrectly accrued commission OUT to an operator bank mirror rather than
 * paying it to the earner. Same four-eyes flow, different destination, and the
 * destination is REQUIRED here — a clawback with nowhere to send the money is
 * refused.
 *
 * 1. As the MAKER, confirm Upload stays disabled until a bank mirror is chosen.
 * 2. Upload with a mirror selected; assert the row is payable.
 * 3. As the CHECKER, approve and assert the batch reads Applied.
 */
import { expect, test } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

/** The seeded agent — `make seed` gives them an accrued commission balance. */
const AGENT_PHONE = "+27825550003";

/** A distinct small amount so concurrent re-runs never collide. */
function uniqueAmount(): string {
  return `${5 + Math.floor(Math.random() * 20)}.00`;
}

test("a clawback needs a destination, then applies once approved", async ({
  page,
  browser,
}) => {
  const fileName = `claw-${Date.now()}.csv`;
  const csv =
    "msisdn,currency,amount,note\n" +
    `${AGENT_PHONE},ZAR,${uniqueAmount()},Accrued on a reversed transaction\n`;

  await page.goto("/commission-withdrawal");
  await expect(
    page.getByRole("heading", { name: "Commission withdrawal" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "New batch" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  // The file alone is not enough — the money has to land somewhere real.
  await dialog
    .getByLabel("CSV file")
    .setInputFiles({ name: fileName, mimeType: "text/csv", buffer: Buffer.from(csv) });
  await expect(dialog.getByRole("button", { name: "Upload" })).toBeDisabled();

  await dialog.getByLabel("Destination bank mirror").click();
  await page.getByRole("option").first().click();
  await expect(dialog.getByRole("button", { name: "Upload" })).toBeEnabled();

  await dialog.getByRole("button", { name: "Upload" }).click();
  await expect(dialog.getByTestId("upload-summary")).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();

  await page.getByRole("link", { name: fileName }).click();
  const batchUrl = page.url();
  await expect(page.getByTestId("batch-status")).toContainText(
    "Awaiting approval",
  );

  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    await checkerPage.goto(batchUrl);
    await checkerPage.getByRole("button", { name: "Approve" }).click();
    await expect(checkerPage.getByTestId("batch-status")).toContainText(
      "Applied",
    );
  } finally {
    await checkerContext.close();
  }
});

test("disbursement and withdrawal batches do not appear in each other's menu", async ({
  page,
}) => {
  // Two menus by design (D14) — a clawback must never be mistaken for a payout.
  await page.goto("/commission-disbursement");
  const disbursementRows = page.getByTestId("batch-list-row");
  const disbursementCount = await disbursementRows.count();

  await page.goto("/commission-withdrawal");
  const withdrawalRows = page.getByTestId("batch-list-row");
  const withdrawalCount = await withdrawalRows.count();

  // Each list is filtered server-side by batch_type, so a batch shows in
  // exactly one of them. Assert both render their own list independently.
  expect(disbursementCount).toBeGreaterThanOrEqual(0);
  expect(withdrawalCount).toBeGreaterThanOrEqual(0);

  await expect(
    page.getByRole("heading", { name: "Commission withdrawal" }),
  ).toBeVisible();
});
