/**
 * Archive the latest Playwright HTML report so past runs stay viewable.
 *
 * Playwright overwrites playwright-report/ on every run, which loses the
 * screenshots/videos of earlier runs. This script copies the just-generated
 * report (self-contained — attachments live in its data/ folder) into
 * ../test-reports/e2e-history/<timestamp>/ and prunes the archive to the most
 * recent KEEP_RUNS runs so always-on video capture doesn't eat the disk.
 *
 * Invoked automatically by `npm run e2e` (after playwright test, regardless of
 * pass/fail). Open any archived run via its index.html.
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** How many archived runs to retain (videos are large; oldest pruned first). */
const KEEP_RUNS = 10;

const adminUiDir = dirname(dirname(fileURLToPath(import.meta.url)));
const reportDir = join(adminUiDir, "playwright-report");
const historyRoot = join(adminUiDir, "..", "test-reports", "e2e-history");

/**
 * Copy the current report into a timestamped archive folder and prune old runs.
 * No-op (with a notice) when no report exists yet.
 */
function archive() {
  if (!existsSync(join(reportDir, "index.html"))) {
    console.log("[e2e-archive] no playwright-report/index.html found — nothing to archive");
    return;
  }

  // Filesystem-safe local timestamp, e.g. 2026-08-19T14-30-05.
  const stamp = new Date()
    .toISOString()
    .replace(/\.\d+Z$/, "")
    .replace(/:/g, "-");
  const dest = join(historyRoot, stamp);

  mkdirSync(historyRoot, { recursive: true });
  cpSync(reportDir, dest, { recursive: true });
  console.log(`[e2e-archive] report archived to ${dest}`);

  // Timestamped names sort chronologically — drop everything past the newest KEEP_RUNS.
  const runs = readdirSync(historyRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort()
    .reverse();
  for (const stale of runs.slice(KEEP_RUNS)) {
    rmSync(join(historyRoot, stale), { recursive: true, force: true });
    console.log(`[e2e-archive] pruned old run ${stale}`);
  }
}

archive();
