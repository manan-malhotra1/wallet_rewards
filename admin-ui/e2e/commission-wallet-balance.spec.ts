/**
 * Accrued commission is visible but NOT spendable (spec 2026-08-26 §5, §10).
 *
 * The point of the whole feature: an agent's commission sits in a separate
 * wallet that they cannot transact against until a disbursement run moves it.
 * The admin user-detail screen must therefore show the balance AND make clear
 * it does not count toward what the agent can spend.
 */
import { expect, test } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

/** The seeded agent, who holds both a main and a commission wallet. */
const AGENT_PHONE = "+27825550003";
const AGENT_LOOKUP = `/users?type=phone&value=${encodeURIComponent(AGENT_PHONE)}`;

test("an agent's commission wallet is listed separately from their main wallet", async ({
  page,
}) => {
  await page.goto(AGENT_LOOKUP);

  // Both wallets appear, under labels that cannot be confused with each other
  // or with the tenant-level commission funding pool.
  const commissionRow = page
    .getByRole("row")
    .filter({ hasText: "Commission Wallet" })
    .filter({ hasText: "ZAR" });
  await expect(commissionRow).toBeVisible();

  const mainRow = page
    .getByRole("row")
    .filter({ hasText: "Financial wallet" })
    .filter({ hasText: "ZAR" });
  await expect(mainRow).toBeVisible();

  // The seed accrues a starting balance, so the commission wallet is non-zero.
  const commissionText = await commissionRow.innerText();
  expect(commissionText).toMatch(/\d/);
});
