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

  // The "Open requests" card's Withdraw uses a native window.confirm — accept.
  page.on("dialog", (d) => void d.accept());

  // ---- Maker: propose the edit -------------------------------------------
  await page.goto("/taxes");
  // "Taxes" also names the empty-state heading — pin to the h1.
  await expect(page.getByRole("heading", { name: "Taxes", level: 1 })).toBeVisible();

  // Self-heal: an aborted earlier run can leave an open tax proposal, which
  // disables the row's Edit (per-scope open-request guard). Withdraw any of
  // ours from the "Open requests" card before proposing afresh.
  const withdraw = page.getByRole("button", { name: "Withdraw" });
  while ((await withdraw.count()) > 0) {
    const before = await withdraw.count();
    await withdraw.first().click();
    await expect.poll(() => withdraw.count()).toBeLessThan(before);
  }

  const zarRow = page.getByRole("row").filter({ hasText: "ZAR" });
  await expect(zarRow).toBeVisible();
  const editButton = zarRow.getByRole("button", { name: "Edit tax config" });
  await expect(editButton).toBeEnabled();
  await editButton.click();

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
    // Status values are the UPPERCASE StatusKeys (lib/approvals-filter.ts).
    await checkerPage.goto("/approvals?tab=configuration&status=PENDING");
    await expect(
      checkerPage.getByRole("heading", { name: "Approvals" }),
    ).toBeVisible();

    // Newest pending tax proposal — open its detail drawer and approve
    // (config approve is a single-step action, no confirm). Scope View to the
    // ROW — a page-level name match would also hit the toolbar's disabled
    // "+ Save as view" button (role-name matching is substring).
    await checkerPage
      .getByRole("row")
      .filter({ hasText: "Tax" })
      .first()
      .getByRole("button", { name: "View" })
      .click();

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
