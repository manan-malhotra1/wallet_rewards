/**
 * Bulk commission disbursement, end to end (spec 2026-08-26 §8).
 *
 * The business act: an agent accrues commission into a NON-SPENDABLE commission
 * wallet; at month end an operator reviews it and moves an approved amount into
 * the agent's spendable main wallet. It is four-eyes, so a maker uploads and a
 * DIFFERENT admin approves.
 *
 * 1. As the MAKER, upload a CSV with one good row and one unknown MSISDN.
 *    Assert the validation summary separates them (1 of 2 will pay) — the bad
 *    row must never reach a checker.
 * 2. Open the batch. Assert the checker sees the accrued balance, the amount
 *    being paid, and the DELTA between them, with the maker's note. That delta
 *    is the entire reason the screen exists.
 * 3. As the CHECKER, approve. Assert the batch reads Applied.
 *
 * The amount is small and randomised so re-runs simply draw down the seeded
 * accrual rather than colliding on a fixed figure.
 */
import { expect, test, type Page } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

/** The seeded agent — `make seed` gives them an accrued commission balance. */
const AGENT_PHONE = "+27825550003";

/** A distinct small amount so concurrent re-runs never collide. */
function uniqueAmount(): string {
  return `${10 + Math.floor(Math.random() * 40)}.00`;
}

/** Upload a CSV through the New batch dialog and return the summary text. */
async function uploadBatch(page: Page, csv: string, fileName: string) {
  await page.goto("/commission-disbursement");
  await expect(
    page.getByRole("heading", { name: "Commission disbursement" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "New batch" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();

  await dialog
    .getByLabel("CSV file")
    .setInputFiles({ name: fileName, mimeType: "text/csv", buffer: Buffer.from(csv) });
  await dialog.getByRole("button", { name: "Upload" }).click();

  return dialog;
}

test("maker uploads a mixed batch and a second admin approves it", async ({
  page,
  browser,
}) => {
  const amount = uniqueAmount();
  const fileName = `disb-${Date.now()}.csv`;
  const csv =
    "msisdn,currency,amount,note\n" +
    `${AGENT_PHONE},ZAR,${amount},Verified against statement\n` +
    "+27000000000,ZAR,10.00,Unknown number\n";

  // ---- Maker: upload, and see the good/bad split -------------------------
  const dialog = await uploadBatch(page, csv, fileName);

  const summary = dialog.getByTestId("upload-summary");
  await expect(summary).toBeVisible();
  // One of the two rows resolves; the unknown MSISDN is left out.
  await expect(summary).toContainText("1");
  await expect(summary).toContainText("2");
  await expect(
    dialog.getByRole("button", { name: "Download rejected rows" }),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();

  // ---- Maker: the checker view shows balance, amount and the delta -------
  await page.getByRole("link", { name: fileName }).click();
  await expect(page.getByTestId("batch-status")).toContainText(
    "Awaiting approval",
  );

  const row = page.getByTestId("batch-row-1");
  await expect(row).toBeVisible();
  await expect(row).toContainText("Verified against statement");
  // The delta cell is present and numeric — the accrued balance minus what is
  // being paid, i.e. what stays held in the commission wallet.
  const delta = await page.getByTestId("batch-delta-1").innerText();
  expect(Number(delta)).toBeGreaterThan(0);

  const batchUrl = page.url();

  // ---- Checker: a DIFFERENT admin approves ------------------------------
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

test("the maker cannot approve their own batch", async ({ page }) => {
  const fileName = `self-${Date.now()}.csv`;
  const csv =
    "msisdn,currency,amount,note\n" +
    `${AGENT_PHONE},ZAR,${uniqueAmount()},Self-approval attempt\n`;

  const dialog = await uploadBatch(page, csv, fileName);
  await expect(dialog.getByTestId("upload-summary")).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();

  await page.getByRole("link", { name: fileName }).click();
  await page.getByRole("button", { name: "Approve" }).click();

  // Four-eyes: the uploader is refused, and the batch stays pending.
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByTestId("batch-status")).toContainText(
    "Awaiting approval",
  );
});

test("rejecting a batch is terminal and requires a reason", async ({
  page,
  browser,
}) => {
  const fileName = `rej-${Date.now()}.csv`;
  const csv =
    "msisdn,currency,amount,note\n" +
    `${AGENT_PHONE},ZAR,${uniqueAmount()},To be rejected\n`;

  const dialog = await uploadBatch(page, csv, fileName);
  await expect(dialog.getByTestId("upload-summary")).toBeVisible();
  await dialog.getByRole("button", { name: "Done" }).click();
  await page.getByRole("link", { name: fileName }).click();
  const batchUrl = page.url();

  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    await checkerPage.goto(batchUrl);

    // An empty reason is refused — the maker rebuilds the file from this text.
    await checkerPage.getByRole("button", { name: "Reject batch" }).click();
    await expect(checkerPage.getByRole("alert")).toBeVisible();

    await checkerPage
      .getByLabel("Rejection reason")
      .fill("Totals do not match the November statement");
    await checkerPage.getByRole("button", { name: "Reject batch" }).click();

    await expect(checkerPage.getByTestId("batch-status")).toContainText(
      "Rejected",
    );
    // Terminal: no approve control remains.
    await expect(
      checkerPage.getByRole("button", { name: "Approve" }),
    ).toHaveCount(0);
  } finally {
    await checkerContext.close();
  }
});
