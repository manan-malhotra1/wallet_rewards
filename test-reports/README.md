# Test report

A single HTML report (`index.html`) over **both** stacks, grouped
section → subsection → test case, with each case's last-3-runs strip, latest
result, duration, and last-updated date.

## Generate

```bash
make report            # run BOTH suites + render (from the repo root)
make report-backend    # backend only  (pytest, records results)
make report-frontend   # frontend only (vitest --reporter=json)
make report-html       # re-render from the last run — no tests re-run (fast)

cd backend  && make test-report      # backend suite + render
cd admin-ui && npm run test:report   # frontend suite + render
```

Open `test-reports/index.html` in a browser. Backend / Frontend are tabs;
"show only failing" filters to red rows.

## How the structure is derived (no bespoke config per test)

| Report level | Backend | Frontend |
|---|---|---|
| **Section** | test directory → friendly label (`section-labels.json`) | top-level `describe()` |
| **Subsection** | test file, labelled by its **module docstring** 1st line | the test file |
| **Test case** | test function, described by its **docstring** 1st line | the `it("…")` title |

So the report reads well only if each test function and each test module keeps a
clear one-line docstring — which the coding guidelines already require. Rename a
noisy section by adding an entry to `section-labels.json`.

## Last 3 runs

`history.json` (committed) stores the last 3 **executions** per test case. Every
suite run appends one entry; re-rendering (`make report-html`) never appends, so
the strip counts real runs, not report builds. Update tests after a change and
the newest dot reflects it on the next run.

## Last updated

Read from git: backend rows show the last-commit date of that **individual test
function** (exact line span via `git log -L`); frontend rows show their **file's**
last-commit date. Cached per file blob hash (`.date-cache.json`) so rebuilds are
fast. A brand-new, not-yet-committed test shows `uncommitted`.

## Files

| File | Tracked? | What |
|---|---|---|
| `history.json` | ✅ committed | rolling last-3 per test |
| `section-labels.json` | ✅ committed | friendly section names |
| `index.html` | ✗ generated | the report |
| `latest.json`, `*-run.json`, `.date-cache.json` | ✗ generated | build intermediates |
