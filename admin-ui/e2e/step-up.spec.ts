/**
 * Motivating flow: maker-checker on a step-up PIN policy.
 *
 * 1. As the MAKER (admin-test), edit a step-up policy's threshold on /step-up
 *    and Propose the change → a "pending approval" toast confirms it entered
 *    the config maker-checker pipeline.
 * 2. The proposal appears on /approvals?tab=configuration filtered to the
 *    step-up config type.
 * 3. In a SECOND context as the CHECKER (admin-approver — a DIFFERENT admin, so
 *    self-approval is not in play), open that request and Approve → its status
 *    moves to APPLIED.
 *
 * Requires at least one seeded step-up policy in the active tenant (see
 * scripts/seed.py / make seed). Selectors are a best-guess from the components
 * and may need tuning on the first live run.
 */
import { test, expect } from "@playwright/test";

import { STORAGE_STATE } from "../playwright.config";

test.use({ storageState: STORAGE_STATE.maker });

test("maker proposes a step-up threshold change; checker approves it", async ({
  page,
  browser,
}) => {
  // The "Open requests" card's Withdraw uses a native window.confirm — accept.
  page.on("dialog", (d) => void d.accept());

  // ---- Maker: propose an edit ----------------------------------------------
  await page.goto("/step-up");
  await expect(page.getByRole("heading", { name: "Step-up PIN" })).toBeVisible();

  // Self-heal: an aborted earlier run can leave an open step-up proposal, which
  // locks that policy's Edit (per-scope open-request guard). Withdraw any of
  // ours from the "Open requests" card before proposing afresh.
  const withdraw = page.getByRole("button", { name: "Withdraw" });
  while ((await withdraw.count()) > 0) {
    const before = await withdraw.count();
    await withdraw.first().click();
    await expect.poll(() => withdraw.count()).toBeLessThan(before);
  }

  // Open the first policy's Edit dialog (proposes an `update`).
  await page.getByRole("button", { name: "Edit policy" }).first().click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Edit step-up policy")).toBeVisible();

  // Bump the threshold to a fresh value so the proposal is a real diff.
  const newThreshold = String(300 + Math.floor(Math.random() * 500));
  await dialog.getByLabel("Threshold").fill(newThreshold);
  await dialog.getByRole("button", { name: "Propose change" }).click();

  // Toast title is "Change proposed — pending approval".
  await expect(page.getByText(/pending approval/i)).toBeVisible();

  // ---- Proposal is visible in the Configuration approvals queue ------------
  // Status values are the UPPERCASE StatusKeys (lib/approvals-filter.ts).
  await page.goto("/approvals?tab=configuration&status=PENDING");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  // At least one pending step-up row in the queue table.
  await expect(
    page.getByRole("row").filter({ hasText: "Step-up" }).first(),
  ).toBeVisible();

  // ---- Checker: a different admin approves ---------------------------------
  const checkerContext = await browser.newContext({
    storageState: STORAGE_STATE.checker,
  });
  const checkerPage = await checkerContext.newPage();
  try {
    await checkerPage.goto("/approvals?tab=configuration&status=PENDING");
    // Open the newest pending step-up request's detail drawer. Scope View to
    // the ROW — a page-level name match would also hit the toolbar's disabled
    // "+ Save as view" button (role-name matching is substring).
    await checkerPage
      .getByRole("row")
      .filter({ hasText: "Step-up" })
      .first()
      .getByRole("button", { name: "View" })
      .click();

    const drawer = checkerPage.getByRole("dialog");
    await expect(drawer.getByRole("button", { name: "Approve" })).toBeVisible();
    await drawer.getByRole("button", { name: "Approve" }).click();

    // Approve confirmation toast; the revalidate closes the drawer, so verify
    // APPLIED under the Applied status segment rather than inside it.
    await expect(checkerPage.getByText(/request approved/i)).toBeVisible();
    await checkerPage
      .getByRole("group", { name: "Filter by status" })
      .getByRole("button", { name: /^Applied/ })
      .click();
    await expect(
      checkerPage.getByRole("row").filter({ hasText: "Step-up" }).first(),
    ).toBeVisible();
  } finally {
    await checkerContext.close();
  }
});
