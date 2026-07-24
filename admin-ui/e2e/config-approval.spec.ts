/**
 * Config maker-checker on a native config page (Epic 24) — the Taxes page.
 *
 * Tax is the simplest single-scope config: one row per (tenant, currency) with
 * a couple of flat rates. This drives an in-place edit through the pipeline:
 *
 * 1. As the MAKER (admin-test), edit the ZAR tax row's "Fee tax %" to a fresh
 *    value and Propose → "Change proposed — pending approval" toast. Nothing is
 *    applied yet (the row shows a "change proposed" status).
 * 2. As the CHECKER (admin-approver — a different admin), approve it under
 *    Approvals → Configuration filtered to the tax config type → APPLIED.
 * 3. Assert the effect: the ZAR row on /taxes now shows the new percentage.
 *
 * The new rate is a random whole-basis-points value, so it renders as a clean
 * 2-decimal percentage and each run picks a distinct, unambiguous target.
 * Because the run always drives its own proposal to APPLIED, the per-scope
 * "open request" guard is released, so re-runs don't trip the disabled-Edit
 * state. This spec is the only one touching /taxes.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

test("maker proposes a ZAR tax-rate change; checker approves and it applies", async ({
  page,
  browser,
}) => {
  // Fresh fee-tax rate: bp in [100, 2000] → decimal for input, "%.2f%%" for the
  // rendered cell (e.g. bp=725 → input "0.0725", cell "7.25%").
  const bp = 100 + Math.floor(Math.random() * 1901);
  const rateDecimal = (bp / 10000).toFixed(4);
  const ratePct = `${(bp / 100).toFixed(2)}%`;

  // ---- Maker: propose the edit -------------------------------------------
  await page.goto("/taxes");
  await expect(page.getByRole("heading", { name: "Taxes" })).toBeVisible();

  const zarRow = page.getByRole("row").filter({ hasText: "ZAR" });
  await expect(zarRow).toBeVisible();
  await zarRow.getByRole("button", { name: "Edit tax config" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Edit tax")).toBeVisible();
  await dialog.getByLabel("Fee tax %").fill(rateDecimal);
  await dialog.getByRole("button", { name: "Propose change" }).click();

  await expect(page.getByText(/pending approval/i)).toBeVisible();

  // ---- Checker: approve under Configuration → Tax ------------------------
  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    await checkerPage.goto(
      "/approvals?tab=configuration&status=pending&config_type=tax",
    );
    await expect(
      checkerPage.getByRole("heading", { name: "Approvals" }),
    ).toBeVisible();

    // Newest proposal for the tax scope — open its detail drawer and approve
    // (config approve is a single-step action, no confirm).
    await checkerPage.getByRole("button", { name: "View" }).first().click();

    const drawer = checkerPage.getByRole("dialog");
    await drawer.getByRole("button", { name: "Approve" }).click();

    await expect(checkerPage.getByText(/request approved/i)).toBeVisible();
    // Approving revalidates + closes the drawer; the APPLIED effect is verified
    // below on the /taxes row.
  } finally {
    await checkerContext.close();
  }

  // ---- Effect: the ZAR tax row reflects the new fee-tax percentage -------
  await expect
    .poll(
      async () => {
        await page.goto("/taxes");
        return page
          .getByRole("row")
          .filter({ hasText: "ZAR" })
          .filter({ hasText: ratePct })
          .count();
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0);
});
