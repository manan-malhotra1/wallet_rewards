"""Build the combined Sasai test report (HTML) from backend + frontend + e2e runs.

Joins raw per-test outcomes (pytest via the conftest recorder → backend-run.json;
vitest --reporter=json → frontend-run.json; Playwright --reporter=json →
e2e-run.json) with:

  * the test's human description (Python: function docstring 1st line via AST;
    frontend: the `it(...)` title),
  * its SECTION (backend: test dir; frontend: top `describe`) and SUBSECTION
    (the test file, labelled by its module docstring / basename),
  * a rolling PASS/FAIL history of the last 3 report builds (test-reports/history.json),
  * a "last updated" date read from git — per test FUNCTION for the backend
    (exact AST line-span → `git log -L`), per FILE for the frontend.

Emits test-reports/index.html (one page: a combined automation Dashboard tab
plus Backend / Frontend / E2E tabs, with expand/collapse-all controls). Each
fresh Playwright run is also archived — JSON plus its screenshot/video/trace
files — under test-reports/e2e-runs/<stamp>/, so the E2E tab offers a run
selector and every test case expands to that run's own artifacts. index.html
and e2e-runs/ are committed: the report is source-controlled evidence. Run via
`make report` (backend + frontend), `make report-e2e` (Playwright, needs the
live stack), or the per-stack make targets. Idempotent; safe to re-run. Pure
reporting — never touches application code or the databases.
"""
# ruff: noqa: E501 — the embedded HTML/CSS/JS template (_HTML_SHELL) has long
# lines that are clearer left unwrapped; line-length isn't meaningful here.

from __future__ import annotations

import ast
import base64
import json
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "test-reports"
HISTORY_PATH = REPORTS_DIR / "history.json"
LABELS_PATH = REPORTS_DIR / "section-labels.json"
DATE_CACHE_PATH = REPORTS_DIR / ".date-cache.json"
LATEST_PATH = REPORTS_DIR / "latest.json"
OUTPUT_PATH = REPORTS_DIR / "index.html"
BACKEND_RUN = REPORTS_DIR / "backend-run.json"
FRONTEND_RUN = REPORTS_DIR / "frontend-run.json"
E2E_RUN = REPORTS_DIR / "e2e-run.json"
# Per-run e2e archive: each fresh Playwright run is stored (run.json + media/)
# under e2e-runs/<stamp>/ and surfaced via the E2E tab's run selector. These
# folders are COMMITTED (screenshots + videos included), so retention is small.
E2E_RUNS_DIR = REPORTS_DIR / "e2e-runs"
E2E_RUNS_KEPT = 5
# Official Sasai logo, inlined as a data URI so the single-file report renders
# the brand everywhere (file://, CI artifacts, the 8377 server) with no asset
# dependency.
LOGO_PATH = REPO_ROOT / "admin-ui" / "public" / "sasai-logo.png"

# All report stacks, in tab order, with their reader-facing labels.
STACKS = ("backend", "frontend", "e2e")
STACK_LABELS = {"backend": "Backend", "frontend": "Frontend", "e2e": "E2E (Playwright)"}
# Cucumber/Gherkin .feature files (committed, not deployed). A Scenario whose
# name matches a test case's "Verify …" description supplies that row's
# expandable Given/When/Then.
FEATURES_DIR = REPO_ROOT / "features"

# How many past executions to keep + show per test case.
HISTORY_LIMIT = 3

# Outcome precedence when aggregating parametrised variants into one scenario:
# a single failure makes the whole scenario fail.
_OUTCOME_RANK = {"failed": 3, "error": 3, "passed": 2, "skipped": 1}


@dataclass
class Scenario:
    """One test case row in the report (parametrised variants aggregated)."""

    stack: str  # "backend" | "frontend" | "e2e"
    section: str  # slug (backend dir) / top describe title (frontend, e2e)
    rel_path: str  # repo-relative test file path
    name: str  # test function name / frontend fullName
    description: str  # one-liner shown to the reader
    subsection_label: str  # file's module-docstring line / basename
    outcome: str = "skipped"
    duration: float = 0.0
    variants: int = 0
    lineno: int | None = None
    end_lineno: int | None = None
    updated: str | None = None  # YYYY-MM-DD (git); None = uncommitted
    history: list[dict[str, str]] = field(default_factory=list)
    # Given/When/Then steps from a matching .feature Scenario (name == description),
    # as (keyword, text) pairs incl. any Background steps; None if no scenario exists.
    gherkin: list[tuple[str, str]] | None = None
    # E2E only: this run's attachments for the case — {"name", "path",
    # "contentType"} dicts, path relative to test-reports/ (into e2e-runs/…/media/).
    artifacts: list[dict[str, str]] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Stable identity across runs — keys the history store."""
        return f"{self.stack}::{self.rel_path}::{self.name}"


# ---------------------------------------------------------------------------
# git helpers (with a per-file blob-hash cache so rebuilds stay fast)
# ---------------------------------------------------------------------------


def _git(args: list[str]) -> str:
    """Run a git command at the repo root; return stdout ('' on any failure)."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
        )
        return out.stdout if out.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        return ""


def _blob_hash(rel_path: str) -> str:
    """Working-tree content hash of a file — the cache key for its git dates."""
    return _git(["hash-object", rel_path]).strip()


def _file_date(rel_path: str) -> str | None:
    """Last commit date (YYYY-MM-DD) touching the whole file, or None."""
    out = _git(["log", "-1", "--format=%cs", "--", rel_path]).strip()
    return out or None


def _func_date(rel_path: str, start: int, end: int) -> str | None:
    """Last commit date (YYYY-MM-DD) touching lines [start, end] of a file.

    Uses `git log -L <start>,<end>:<file>` which tracks that exact line span
    through history; the first `%cs` line is the most recent change. None when
    the span has no committed history (e.g. a brand-new uncommitted test).
    """
    if not start or not end:
        return None
    out = _git(["log", "-1", "--format=%cs", f"-L{start},{end}:{rel_path}"])
    for line in out.splitlines():
        line = line.strip()
        if line and line[:4].isdigit():
            return line
    return None


# ---------------------------------------------------------------------------
# AST: per-file test function spans + docstrings
# ---------------------------------------------------------------------------


def _parse_python_file(rel_path: str) -> tuple[str | None, dict[str, dict[str, object]]]:
    """Return (module-docstring-1st-line, {func_name: {doc, lineno, end_lineno}}).

    Only module-level `test_*` functions are collected (the project's tests are
    flat functions, never classes). Docstring is the trimmed first line.
    """
    path = REPO_ROOT / rel_path
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None, {}
    module_doc = _first_line(ast.get_docstring(tree))
    funcs: dict[str, dict[str, object]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            funcs[node.name] = {
                "doc": _first_line(ast.get_docstring(node)) or _humanise(node.name),
                "lineno": node.lineno,
                "end_lineno": node.end_lineno or node.lineno,
            }
    return module_doc, funcs


def _first_line(text: str | None) -> str | None:
    """First non-empty line of a (docstring) block, trimmed."""
    if not text:
        return None
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return None


def _humanise(slug: str) -> str:
    """Turn a slug like `test_add_limit` / `config_requests` into a title."""
    slug = slug.removeprefix("test_")
    return slug.replace("_", " ").replace("-", " ").strip().capitalize() or slug


# ---------------------------------------------------------------------------
# Load raw runs → Scenario list
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> object | None:
    """Parse a JSON file, or None if it's missing/unreadable."""
    if not path.exists():
        return None
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError):
        return None


def _better(a: str, b: str) -> str:
    """Return the higher-precedence outcome of two (failure beats pass)."""
    return a if _OUTCOME_RANK.get(a, 0) >= _OUTCOME_RANK.get(b, 0) else b


@dataclass
class _Agg:
    """Accumulator for a scenario's parametrised variants (one file::func)."""

    outcome: str = "skipped"
    duration: float = 0.0
    variants: int = 0


def _collect_backend() -> list[Scenario]:
    """Build backend scenarios from backend-run.json, aggregating parametrised ids."""
    raw = _load_json(REPORTS_DIR / "backend-run.json")
    if not isinstance(raw, dict):
        return []
    # Group nodeids by (file, func), summing durations + worst-casing outcome.
    grouped: dict[tuple[str, str], _Agg] = {}
    for nodeid, res in raw.items():
        file_part, _, func_part = nodeid.partition("::")
        if not func_part:
            continue
        func = func_part.split("[", 1)[0]  # strip parametrise id
        rel_path = f"backend/{file_part}" if not file_part.startswith("backend/") else file_part
        g = grouped.setdefault((rel_path, func), _Agg())
        g.outcome = _better(g.outcome, str(res.get("outcome", "skipped")))
        g.duration += float(res.get("duration", 0.0))
        g.variants += 1

    scenarios: list[Scenario] = []
    ast_cache: dict[str, tuple[str | None, dict[str, dict[str, object]]]] = {}
    for (rel_path, func), g in grouped.items():
        if rel_path not in ast_cache:
            ast_cache[rel_path] = _parse_python_file(rel_path)
        module_doc, funcs = ast_cache[rel_path]
        meta = funcs.get(func, {})
        section = rel_path.split("/")[2] if rel_path.count("/") >= 2 else "misc"
        scenarios.append(
            Scenario(
                stack="backend",
                section=section,
                rel_path=rel_path,
                name=func,
                description=str(meta.get("doc") or _humanise(func)),
                subsection_label=module_doc or Path(rel_path).name,
                outcome=g.outcome,
                duration=round(g.duration, 3),
                variants=g.variants,
                lineno=meta.get("lineno"),  # type: ignore[arg-type]
                end_lineno=meta.get("end_lineno"),  # type: ignore[arg-type]
            )
        )
    return scenarios


def _collect_frontend() -> list[Scenario]:
    """Build frontend scenarios from a vitest --reporter=json dump."""
    raw = _load_json(REPORTS_DIR / "frontend-run.json")
    if not isinstance(raw, dict):
        return []
    scenarios: list[Scenario] = []
    for file_result in raw.get("testResults", []):
        abs_name = str(file_result.get("name", ""))
        rel_path = _relativise(abs_name)
        for a in file_result.get("assertionResults", []):
            ancestors = list(a.get("ancestorTitles", []))
            title = str(a.get("title", ""))
            section = ancestors[0] if ancestors else Path(rel_path).stem
            desc = " › ".join([*ancestors[1:], title]) if ancestors else title  # noqa: RUF001
            scenarios.append(
                Scenario(
                    stack="frontend",
                    section=section,
                    rel_path=rel_path,
                    name=str(a.get("fullName") or f"{' '.join(ancestors)} {title}").strip(),
                    description=desc or title,
                    subsection_label=Path(rel_path).name,
                    outcome=_norm_vitest(str(a.get("status", "skipped"))),
                    duration=round(float(a.get("duration") or 0.0) / 1000.0, 3),
                    variants=1,
                )
            )
    return scenarios


def _relativise(abs_path: str) -> str:
    """Make an absolute test path repo-relative (best effort)."""
    try:
        return str(Path(abs_path).resolve().relative_to(REPO_ROOT))
    except (ValueError, OSError):
        # Fall back to the admin-ui-relative path if it's outside the repo view.
        return abs_path


def _norm_vitest(status: str) -> str:
    """Map vitest statuses onto the shared outcome vocabulary."""
    return {"passed": "passed", "failed": "failed", "skipped": "skipped", "pending": "skipped"}.get(
        status, "skipped"
    )


def _e2e_scenarios(raw: dict[str, object]) -> list[Scenario]:
    """Build e2e scenarios from one Playwright `--reporter=json` run dict.

    Playwright nests suites: the top level is one suite per spec FILE, with
    `describe` blocks as child suites. Each spec carries one test per project;
    the `setup` project (auth bootstrap) is excluded — it isn't a product test.
    A spec's outcome comes from its test status: expected→passed,
    unexpected→failed, flaky→passed (it passed on retry), skipped→skipped.
    Each test's attachments (screenshot/video/trace) ride along on the scenario
    so the report can attach them to that exact case.
    """
    scenarios: list[Scenario] = []

    def walk(suite: dict[str, object], ancestors: list[str]) -> None:
        """Recurse one Playwright suite, accumulating describe-title ancestry."""
        file_rel = str(suite.get("file", ""))
        title = str(suite.get("title", ""))
        # File-level suites use the filename as their title — not a describe.
        next_ancestors = ancestors if not title or title == file_rel else [*ancestors, title]
        for spec in suite.get("specs", []):  # type: ignore[union-attr]
            if not isinstance(spec, dict):
                continue
            outcome, duration = "skipped", 0.0
            counted = 0
            artifacts: list[dict[str, str]] = []
            for test in spec.get("tests", []):
                if not isinstance(test, dict) or test.get("projectName") == "setup":
                    continue
                counted += 1
                outcome = _better(outcome, _norm_playwright(str(test.get("status", "skipped"))))
                for res in test.get("results", []):
                    if isinstance(res, dict):
                        duration += float(res.get("duration") or 0.0)
                        for att in res.get("attachments", []):
                            if isinstance(att, dict) and att.get("path"):
                                artifacts.append(
                                    {
                                        "name": str(att.get("name", "attachment")),
                                        "path": str(att["path"]),
                                        "contentType": str(att.get("contentType", "")),
                                    }
                                )
            if not counted:
                continue
            spec_title = str(spec.get("title", ""))
            rel_path = f"admin-ui/e2e/{file_rel}" if file_rel else "admin-ui/e2e"
            # Fallback section (spec file with no describe): "treasury-adjust.spec.ts"
            # → "Treasury adjust" (split on the first dot to drop ".spec.ts").
            section = (
                next_ancestors[0] if next_ancestors else _humanise(Path(file_rel).name.split(".")[0])
            )
            desc = " › ".join([*next_ancestors[1:], spec_title]) or spec_title  # noqa: RUF001
            scenarios.append(
                Scenario(
                    stack="e2e",
                    section=section,
                    rel_path=rel_path,
                    name=" › ".join([*next_ancestors, spec_title]).strip(),  # noqa: RUF001
                    description=desc,
                    subsection_label=Path(rel_path).name,
                    outcome=outcome,
                    duration=round(duration / 1000.0, 3),
                    variants=counted,
                    artifacts=artifacts,
                )
            )
        for child in suite.get("suites", []):  # type: ignore[union-attr]
            if isinstance(child, dict):
                walk(child, next_ancestors)

    for top in raw.get("suites", []):  # type: ignore[union-attr]
        if isinstance(top, dict):
            walk(top, [])
    return scenarios


def _snapshot_e2e_run() -> None:
    """Archive a fresh e2e-run.json plus its media into e2e-runs/<stamp>/.

    Playwright wipes its outputDir (test-reports/e2e-artifacts) at the start of
    every run, so THIS run's screenshots/videos/traces are copied into the
    snapshot's media/ folder and every attachment path inside the stored
    run.json is rewritten to a test-reports-relative path. The archive is
    pruned to the newest E2E_RUNS_KEPT runs (it's committed to git — keep it
    small). No-op when no fresh run file exists.
    """
    raw = _load_json(E2E_RUN)
    if not isinstance(raw, dict):
        return
    stats = raw.get("stats")
    start = str((stats or {}).get("startTime") if isinstance(stats, dict) else "") or (
        datetime.now().isoformat()
    )
    # "2026-08-19T23:53:01.123Z" → filesystem-safe "2026-08-19T23-53-01".
    stamp = start[:19].replace(":", "-")
    media_dir = E2E_RUNS_DIR / stamp / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    def rewrite(suite: dict[str, object]) -> None:
        """Copy every attachment under this suite; rewrite its path in place."""
        for spec in suite.get("specs", []):  # type: ignore[union-attr]
            if not isinstance(spec, dict):
                continue
            for test in spec.get("tests", []):
                if not isinstance(test, dict):
                    continue
                for res in test.get("results", []):
                    if not isinstance(res, dict):
                        continue
                    kept = []
                    for att in res.get("attachments", []):
                        if not isinstance(att, dict) or not att.get("path"):
                            continue
                        src = Path(str(att["path"]))
                        if not src.is_file():
                            continue
                        # Playwright gives each test its own output dir, so
                        # parent-dir + filename is unique AND self-describing.
                        fname = f"{src.parent.name}__{src.name}"
                        if not (media_dir / fname).exists():
                            shutil.copy2(src, media_dir / fname)
                        att["path"] = f"e2e-runs/{stamp}/media/{fname}"
                        kept.append(att)
                    res["attachments"] = kept
        for child in suite.get("suites", []):  # type: ignore[union-attr]
            if isinstance(child, dict):
                rewrite(child)

    for top in raw.get("suites", []):  # type: ignore[union-attr]
        if isinstance(top, dict):
            rewrite(top)
    (E2E_RUNS_DIR / stamp / "run.json").write_text(
        json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8"
    )
    run_dirs = sorted((p for p in E2E_RUNS_DIR.iterdir() if p.is_dir()), reverse=True)
    for stale in run_dirs[E2E_RUNS_KEPT:]:
        shutil.rmtree(stale, ignore_errors=True)


def _load_e2e_runs() -> list[tuple[str, list[Scenario]]]:
    """Load every archived e2e run, newest first, as (stamp, scenarios) pairs."""
    runs: list[tuple[str, list[Scenario]]] = []
    if not E2E_RUNS_DIR.exists():
        return runs
    for run_dir in sorted((p for p in E2E_RUNS_DIR.iterdir() if p.is_dir()), reverse=True):
        raw = _load_json(run_dir / "run.json")
        if isinstance(raw, dict):
            runs.append((run_dir.name, _e2e_scenarios(raw)))
    return runs


def _norm_playwright(status: str) -> str:
    """Map Playwright test statuses onto the shared outcome vocabulary."""
    return {
        "expected": "passed",
        "unexpected": "failed",
        "flaky": "passed",  # passed on retry — green, the flake shows in duration/history
        "skipped": "skipped",
    }.get(status, "skipped")


# ---------------------------------------------------------------------------
# History + dates
# ---------------------------------------------------------------------------


_SCENARIO_FIELDS = (
    "stack",
    "section",
    "rel_path",
    "name",
    "description",
    "subsection_label",
    "outcome",
    "duration",
    "variants",
    "lineno",
    "end_lineno",
    "artifacts",
)


def _save_latest(scenarios: list[Scenario]) -> None:
    """Persist the current scenario set so a re-render needs no test re-run."""
    data = [{f: getattr(s, f) for f in _SCENARIO_FIELDS} for s in scenarios]
    LATEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _load_latest() -> list[dict[str, object]]:
    """Load the last persisted scenario set (empty if none)."""
    data = _load_json(LATEST_PATH)
    return data if isinstance(data, list) else []


def _refresh_source_descriptions(scenarios: list[Scenario]) -> None:
    """Re-read each BACKEND scenario's description + subsection label from source.

    Descriptions are the test function's docstring first line and subsections are
    the module docstring — both live in the .py files, so a re-render reflects
    docstring edits without needing a fresh test run. Frontend descriptions are
    the `it(...)` titles (only available from a vitest run), so they're left as
    carried. A scenario whose function/file can't be parsed keeps its stored text.
    """
    cache: dict[str, tuple[str | None, dict[str, dict[str, object]]]] = {}
    for scn in scenarios:
        if scn.stack != "backend":
            continue
        if scn.rel_path not in cache:
            cache[scn.rel_path] = _parse_python_file(scn.rel_path)
        module_doc, funcs = cache[scn.rel_path]
        meta = funcs.get(scn.name)
        if meta and meta.get("doc"):
            scn.description = str(meta["doc"])
        if module_doc:
            scn.subsection_label = module_doc


def _apply_history(scenarios: list[Scenario], stacks_run: set[str]) -> None:
    """Append this EXECUTION's outcome to each scenario's rolling last-3 history.

    Only scenarios in a stack that actually ran this build are appended; a stack
    that wasn't run carries its stored history forward unchanged (so a
    frontend-only build never blanks the backend column). The caller consumes
    (deletes) the run files afterwards, so re-rendering never re-appends a run —
    the strip counts test EXECUTIONS, not report renders.
    """
    history = _load_json(HISTORY_PATH)
    history = history if isinstance(history, dict) else {}
    stamp = datetime.now().isoformat(timespec="seconds")

    by_key = {s.key: s for s in scenarios}
    # Append current outcomes for the stacks that ran.
    for scn in scenarios:
        if scn.stack not in stacks_run:
            continue
        past = list(history.get(scn.key, []))
        past.append({"date": stamp, "outcome": scn.outcome})
        history[scn.key] = past[-HISTORY_LIMIT:]

    # Hydrate every scenario's display history from the store.
    for key, past in history.items():
        if key in by_key:
            by_key[key].history = list(past)[-HISTORY_LIMIT:]

    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _apply_dates(scenarios: list[Scenario]) -> None:
    """Fill each scenario's `updated` date from git, cached per file blob hash.

    Backend rows get a per-FUNCTION date (exact AST span → `git log -L`); frontend
    rows share their file's last-commit date. The cache keys on the file's current
    blob hash, so unchanged files skip all git work on the next build.
    """
    cache = _load_json(DATE_CACHE_PATH)
    cache = cache if isinstance(cache, dict) else {}
    files = {s.rel_path for s in scenarios}
    fresh: dict[str, dict[str, object]] = {}

    for rel_path in files:
        blob = _blob_hash(rel_path)
        entry = cache.get(rel_path)
        if isinstance(entry, dict) and entry.get("blob") == blob and blob:
            fresh[rel_path] = entry
            continue
        fresh[rel_path] = {"blob": blob, "file": _file_date(rel_path), "funcs": {}}

    for scn in scenarios:
        entry = fresh[scn.rel_path]
        funcs = entry.get("funcs")
        if not isinstance(funcs, dict):
            funcs = {}
            entry["funcs"] = funcs
        file_date = entry.get("file")
        if scn.stack == "backend" and scn.lineno:
            if scn.name not in funcs:
                funcs[scn.name] = _func_date(scn.rel_path, scn.lineno, scn.end_lineno or scn.lineno)
            scn.updated = funcs.get(scn.name) or file_date  # type: ignore[assignment]
        else:
            scn.updated = file_date  # type: ignore[assignment]

    DATE_CACHE_PATH.write_text(json.dumps(fresh, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Gherkin (.feature) — Given/When/Then scenarios keyed by "Verify …" name
# ---------------------------------------------------------------------------

_STEP_KEYWORDS = ("Given", "When", "Then", "And", "But", "*")


def _norm(text: str) -> str:
    """Normalise a scenario/description string for matching.

    Collapses whitespace, lowercases, and strips trailing sentence punctuation so
    a docstring "Verify X." matches a Scenario named "Verify X".
    """
    return " ".join(text.split()).lower().rstrip(".!")


def _load_gherkin() -> dict[str, list[tuple[str, str]]]:
    """Parse every features/**/*.feature into {normalised scenario name: steps}.

    Steps are (keyword, text) pairs; a feature's `Background:` steps are prepended
    to each of that feature's scenarios so a row shows its full setup. Matching is
    by scenario NAME == the test case's "Verify …" description (normalised). A
    minimal hand-rolled parser — no external Cucumber dependency.
    """
    scenarios: dict[str, list[tuple[str, str]]] = {}
    if not FEATURES_DIR.exists():
        return scenarios
    for path in sorted(FEATURES_DIR.rglob("*.feature")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        background: list[tuple[str, str]] = []
        current_name: str | None = None
        bucket: list[tuple[str, str]] | None = None
        target = "scenario"  # or "background"
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("@"):
                continue
            if line.startswith("Feature:"):
                continue
            if line.startswith("Background:"):
                target, background = "background", []
                current_name = None
                continue
            if line.startswith("Scenario:") or line.startswith("Scenario Outline:"):
                current_name = line.split(":", 1)[1].strip()
                bucket = list(background)
                scenarios[_norm(current_name)] = bucket
                target = "scenario"
                continue
            keyword = next((k for k in _STEP_KEYWORDS if line.startswith(k + " ")), None)
            if keyword is None:
                continue
            step = (keyword, line[len(keyword) :].strip())
            if target == "background":
                background.append(step)
            elif bucket is not None:
                bucket.append(step)
    return scenarios


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _logo_data_uri() -> str:
    """Inline the Sasai logo PNG as a data URI ('' when the asset is missing)."""
    try:
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _labels() -> dict[str, dict[str, str]]:
    """Load the friendly section-label registry (empty-safe)."""
    data = _load_json(LABELS_PATH)
    return data if isinstance(data, dict) else {}


def _section_label(labels: dict[str, dict[str, str]], stack: str, slug: str) -> str:
    """Friendly section name.

    Backend sections are dir slugs → mapped to a friendly label (else title-cased).
    Frontend/e2e sections are `describe(...)` titles — already prose — so they
    render verbatim when unmapped, never title-cased.
    """
    mapped = labels.get(stack, {}).get(slug)
    if mapped:
        return mapped
    return _humanise(slug) if stack == "backend" else slug


def _dots(history: list[dict[str, str]]) -> str:
    """Render the last-3 pass/fail strip (oldest→newest, left-padded)."""
    slots = [None] * (HISTORY_LIMIT - len(history)) + [h.get("outcome") for h in history]
    out = []
    for slot in slots[-HISTORY_LIMIT:]:
        cls = {"passed": "p", "failed": "f", "error": "f", "skipped": "s"}.get(slot or "", "n")
        title = slot or "not run"
        out.append(f'<span class="dot {cls}" title="{escape(title)}"></span>')
    return "".join(out)


def _render(scenarios: list[Scenario], e2e_runs: list[tuple[str, list[Scenario]]]) -> str:
    """Render the full self-contained HTML page (Dashboard tab + one per stack).

    The E2E tab is special: when archived runs exist it renders a run selector
    with one artifact-rich block per run instead of the plain stack view.
    """
    labels = _labels()
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    stacks: dict[str, list[Scenario]] = {stack: [] for stack in STACKS}
    for scn in scenarios:
        stacks.setdefault(scn.stack, []).append(scn)

    tabs = ['<button class="tab active" data-stack="dashboard">Dashboard</button>']
    panels = [
        f'<div class="panel active" data-stack="dashboard">{_render_dashboard(stacks, labels)}</div>'
    ]
    for stack in STACKS:
        items = stacks.get(stack, [])
        passed = sum(1 for s in items if s.outcome == "passed")
        failed = sum(1 for s in items if s.outcome in ("failed", "error"))
        total = len(items)
        badge = (f"{passed}/{total} ✓" + (f" · {failed} ✗" if failed else "")) if total else "not run"
        tabs.append(
            f'<button class="tab" data-stack="{stack}">'
            f"{escape(STACK_LABELS[stack])} <span class=\"muted\">{escape(badge)}</span></button>"
        )
        body = (
            _render_e2e(e2e_runs, labels)
            if stack == "e2e" and e2e_runs
            else _render_stack(stack, items, labels)
        )
        panels.append(f'<div class="panel" data-stack="{stack}">{body}</div>')

    return _HTML_SHELL.format(
        generated=escape(generated),
        tabs="".join(tabs),
        panels="".join(panels),
        logo=_logo_data_uri(),
    )


# --- Dashboard tab -----------------------------------------------------------


def _stack_stats(items: list[Scenario]) -> dict[str, object]:
    """Aggregate one stack's scenarios into the numbers the dashboard shows."""
    passed = sum(1 for s in items if s.outcome == "passed")
    failed = sum(1 for s in items if s.outcome in ("failed", "error"))
    skipped = len(items) - passed - failed
    total = len(items)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "rate": (100.0 * passed / total) if total else 0.0,
        "duration": sum(s.duration for s in items),
        "last_run": max(
            (h["date"] for s in items for h in s.history if h.get("date")), default=None
        ),
    }


def _run_strip(items: list[Scenario]) -> str:
    """Aggregate the stack's last-3 EXECUTIONS into one pass/fail dot strip.

    History entries share a per-build timestamp, so grouping by date recovers
    the executions; an execution is red if any of its tests failed.
    """
    by_stamp: dict[str, str] = {}
    for scn in items:
        for h in scn.history:
            stamp = str(h.get("date", ""))
            if stamp:
                by_stamp[stamp] = _better(by_stamp.get(stamp, "skipped"), str(h.get("outcome")))
    stamps = sorted(by_stamp)[-HISTORY_LIMIT:]
    runs = [(s, by_stamp[s]) for s in stamps]
    slots: list[tuple[str, str] | None] = [None] * (HISTORY_LIMIT - len(runs)) + runs  # type: ignore[list-item]
    out = []
    for slot in slots:
        if slot is None:
            out.append('<span class="dot n" title="not run"></span>')
        else:
            stamp, outcome = slot
            cls = {"passed": "p", "failed": "f", "error": "f"}.get(outcome, "s")
            out.append(f'<span class="dot {cls}" title="{escape(stamp)}: {escape(outcome)}"></span>')
    return "".join(out)


def _bar(stats: dict[str, object]) -> str:
    """Render a pass/fail/skip proportion bar for one stat block."""
    total = int(stats["total"]) or 1  # type: ignore[call-overload]
    segs = []
    for key, cls in (("passed", "p"), ("failed", "f"), ("skipped", "s")):
        n = int(stats[key])  # type: ignore[call-overload]
        if n:
            segs.append(f'<span class="seg {cls}" style="width:{100.0 * n / total:.2f}%"></span>')
    return f'<div class="bar">{"".join(segs)}</div>'


def _card(
    title: str, stats: dict[str, object], strip: str, empty_hint: str = "", stack: str = ""
) -> str:
    """Render one dashboard stat card (overall or per stack).

    When `stack` is given the card is clickable and navigates to that stack's tab.
    """
    attrs = f' data-stack="{escape(stack)}" role="button" tabindex="0"' if stack else ""
    total = int(stats["total"])  # type: ignore[call-overload]
    if not total:
        return (
            f'<div class="card"{attrs}><div class="card-title">{escape(title)}</div>'
            f'<div class="card-rate muted">n/a</div>'
            f'<div class="card-sub muted">{escape(empty_hint or "no results yet")}</div></div>'
        )
    failed = int(stats["failed"])  # type: ignore[call-overload]
    skipped = int(stats["skipped"])  # type: ignore[call-overload]
    duration = float(stats["duration"])  # type: ignore[arg-type]
    last_run = stats["last_run"]
    bits = [f"{stats['passed']}/{total} passed"]
    if failed:
        bits.append(f'<span class="fail-txt">{failed} failed</span>')
    if skipped:
        bits.append(f"{skipped} skipped")
    rate_cls = " fail-txt" if failed else ""
    meta = f"{duration:.0f}s"
    if isinstance(last_run, str):
        meta += f" · last run {escape(last_run[:16].replace('T', ' '))}"
    return (
        f'<div class="card"{attrs}><div class="card-title">{escape(title)}'
        f'<span class="card-strip">{strip}</span></div>'
        f'<div class="card-rate{rate_cls}">{float(stats["rate"]):.1f}%</div>'  # type: ignore[arg-type]
        f'{_bar(stats)}'
        f'<div class="card-sub">{" · ".join(bits)}</div>'
        f'<div class="card-sub muted">{meta}</div></div>'
    )


# Reader-facing explanation of how each suite executes, shown on the Dashboard
# tab. Static prose (not derived from code) — update alongside harness changes.
_SUITE_NOTES = (
    (
        "Backend · pytest (API tests)",
        "Tests in <code>backend/tests/</code> call the FastAPI endpoints and services "
        "directly in-process against a test database; no browser or running server. They "
        "cover happy paths, auth failures, tenant isolation, idempotency and ledger "
        "invariants. <code>make report-backend</code> runs pytest with the "
        "<code>SASAI_TEST_REPORT=1</code> recorder, which writes every outcome to "
        "<code>test-reports/backend-run.json</code>.",
    ),
    (
        "Frontend · Vitest (unit/component tests)",
        "<code>*.test.ts(x)</code> files co-located with the admin-ui source render "
        "components into a simulated DOM (jsdom) with Testing Library; server actions are "
        "mocked, so neither a browser nor the backend is needed. They cover lib helpers and "
        "the interactive maker-checker components. <code>make report-frontend</code> runs "
        "Vitest's JSON reporter into <code>test-reports/frontend-run.json</code>.",
    ),
    (
        "E2E · Playwright (real browser, live stack)",
        "<code>admin-ui/e2e/*.spec.ts</code> drive a real Chromium through the actual "
        "Next.js app against the live backend and Keycloak, so the whole stack must be up. "
        "A <code>setup</code> project logs the maker and checker admins in once and saves "
        "their storage state, so specs start authenticated; specs run serially because "
        "maker-checker flows share backend state. Every test records a screenshot and video "
        "(plus a trace on failure); each run is archived with its artifacts under "
        "<code>test-reports/e2e-runs/</code> and selectable on the E2E tab, where every test "
        "case expands to its own artifacts. <code>make report-e2e</code> runs the suite and "
        "rebuilds this page.",
    ),
    (
        "How they combine",
        "Each run leaves its JSON file in <code>test-reports/</code>; "
        "<code>scripts/build_test_report.py</code> merges whatever run files exist with git "
        "dates, Gherkin scenarios and the rolling last-3 history into this page. A stack "
        "that didn't run carries its previous results forward, so one suite can be "
        "refreshed without blanking the others.",
    ),
)


def _render_suite_notes() -> str:
    """Render the collapsed 'How these suites run' explainer for the dashboard."""
    blocks = "".join(
        f'<div class="note"><div class="note-title">{title}</div><p>{body}</p></div>'
        for title, body in _SUITE_NOTES
    )
    return (
        '<details class="section"><summary>'
        '<span class="sec-name">How these suites run</span>'
        '<span class="sec-stat">pytest · Vitest · Playwright</span></summary>'
        f'<div class="sub notes">{blocks}</div></details>'
    )


def _render_dashboard(stacks: dict[str, list[Scenario]], labels: dict[str, dict[str, str]]) -> str:
    """Render the combined automation dashboard: cards, failures, section grid."""
    everything = [s for stack in STACKS for s in stacks.get(stack, [])]
    cards = [_card("All automation", _stack_stats(everything), _run_strip(everything))]
    for stack in STACKS:
        items = stacks.get(stack, [])
        hint = "run `make report-e2e` (needs the live stack)" if stack == "e2e" else "no results yet"
        cards.append(
            _card(STACK_LABELS[stack], _stack_stats(items), _run_strip(items), hint, stack=stack)
        )

    # Failing tests across every stack — each row jumps to its tab.
    fails = [
        (stack, scn)
        for stack in STACKS
        for scn in stacks.get(stack, [])
        if scn.outcome in ("failed", "error")
    ]
    fails.sort(key=lambda t: (t[0], t[1].section.lower(), t[1].description.lower()))
    if fails:
        rows = "".join(
            f'<button class="fail-link" data-stack="{stack}">'
            f'<span class="pill f">FAIL</span>'
            f'<span class="fail-desc">{escape(scn.description)}</span>'
            f'<span class="muted">{escape(STACK_LABELS[stack])} · '
            f"{escape(_section_label(labels, stack, scn.section))}</span></button>"
            for stack, scn in fails
        )
        failures = (
            f'<h2>Failing tests <span class="muted">({len(fails)})</span></h2>'
            f'<div class="fail-list">{rows}</div>'
        )
    else:
        failures = '<h2>Failing tests</h2><p class="all-green">✓ No failing tests across any suite.</p>'

    # Per-stack section breakdown, collapsed by default to keep the page calm.
    breakdowns = []
    for stack in STACKS:
        items = stacks.get(stack, [])
        if not items:
            continue
        by_section: dict[str, list[Scenario]] = defaultdict(list)
        for scn in items:
            by_section[scn.section].append(scn)
        rows = []
        for section in sorted(by_section, key=lambda s: _section_label(labels, stack, s).lower()):
            stats = _stack_stats(by_section[section])
            failed = int(stats["failed"])  # type: ignore[call-overload]
            counts = f"{stats['passed']}/{stats['total']}"
            fail_txt = f' · <span class="fail-txt">{failed} ✗</span>' if failed else ""
            rows.append(
                f"<tr><td>{escape(_section_label(labels, stack, section))}</td>"
                f'<td class="num">{counts}{fail_txt}</td>'
                f'<td class="bar-cell">{_bar(stats)}</td></tr>'
            )
        breakdowns.append(
            f'<details class="section"><summary>'
            f'<span class="sec-name">{escape(STACK_LABELS[stack])} · by section</span>'
            f'<span class="sec-stat">{len(by_section)} sections</span></summary>'
            f'<div class="sub"><table class="dash-table"><tbody>{"".join(rows)}</tbody></table></div>'
            f"</details>"
        )

    return (
        f'<div class="cards">{"".join(cards)}</div>'
        f"{failures}"
        f"<h2>Coverage by section</h2>{''.join(breakdowns)}"
        f"<h2>About</h2>{_render_suite_notes()}"
    )


def _pretty_stamp(stamp: str) -> str:
    """Turn a run-folder stamp ("2026-08-19T23-53-01") into "2026-08-19 23:53"."""
    date, _, time = stamp.partition("T")
    return f"{date} {time[:5].replace('-', ':')}" if time else stamp


def _render_e2e(e2e_runs: list[tuple[str, list[Scenario]]], labels: dict[str, dict[str, str]]) -> str:
    """Render the E2E tab: run selector + one artifact-rich block per archived run.

    The newest run gets the full columns (history dots, git dates); older runs
    show just that execution's outcome/time — their history columns would
    misleadingly describe the PRESENT, not that run.
    """
    options, blocks = [], []
    for i, (stamp, scns) in enumerate(e2e_runs):
        passed = sum(1 for s in scns if s.outcome == "passed")
        failed = sum(1 for s in scns if s.outcome in ("failed", "error"))
        mins = sum(s.duration for s in scns) / 60.0
        label = f"{_pretty_stamp(stamp)} · {passed}/{len(scns)} passed"
        if failed:
            label += f" · {failed} failed"
        label += f" · {mins:.1f}m"
        if i == 0:
            label += " (latest)"
        options.append(f'<option value="{escape(stamp)}">{escape(label)}</option>')
        blocks.append(
            f'<div class="e2e-run{" active" if i == 0 else ""}" data-run="{escape(stamp)}">'
            f"{_render_stack('e2e', scns, labels, show_meta=i == 0)}</div>"
        )
    return (
        '<div class="run-bar"><label for="e2e-run-select">Run</label>'
        f'<select id="e2e-run-select">{"".join(options)}</select>'
        '<span class="muted">Expand a test case to see the screenshots, video and trace '
        "captured during the selected run.</span></div>" + "".join(blocks)
    )


def _render_stack(
    stack: str, items: list[Scenario], labels: dict[str, dict[str, str]], show_meta: bool = True
) -> str:
    """Render one stack's collapsible sections → subsections → case rows.

    `show_meta=False` (older archived e2e runs) drops the rolling-history and
    git-date columns, which only describe the CURRENT state of the suite.
    """
    if not items:
        return '<p class="empty">No results yet — run the tests to populate this tab.</p>'

    by_section: dict[str, list[Scenario]] = defaultdict(list)
    for scn in items:
        by_section[scn.section].append(scn)

    blocks = []
    for section in sorted(by_section, key=lambda s: _section_label(labels, stack, s).lower()):
        rows_scn = by_section[section]
        passed = sum(1 for s in rows_scn if s.outcome == "passed")
        failed = sum(1 for s in rows_scn if s.outcome in ("failed", "error"))
        stat = f"{passed} passed" + (f" · {failed} failed" if failed else "")
        sec_cls = " has-fail" if failed else ""

        by_sub: dict[str, list[Scenario]] = defaultdict(list)
        for scn in rows_scn:
            by_sub[scn.rel_path].append(scn)

        sub_html = []
        for rel_path in sorted(by_sub):
            subs = by_sub[rel_path]
            label = subs[0].subsection_label
            rows = "".join(
                _render_row(s, show_meta) for s in sorted(subs, key=lambda s: s.description.lower())
            )
            # Backend: show the file + its module-docstring (a section spans many
            # files). Frontend/e2e: each section IS one file (top describe), so a
            # filename header would just repeat noise — show the cases directly.
            head = (
                ""
                if stack != "backend"
                else f'<div class="sub-head" title="{escape(rel_path)}">'
                f'<span class="sub-file">{escape(Path(rel_path).name)}</span>'
                f'<span class="sub-desc">{escape(label)}</span></div>'
            )
            heads = "<th>Test case</th>"
            heads += "<th>Last 3 runs</th>" if show_meta else ""
            heads += "<th>Latest</th><th>Time</th>" if show_meta else "<th>Result</th><th>Time</th>"
            heads += "<th>Updated</th>" if show_meta else ""
            sub_html.append(
                f'<div class="sub">{head}'
                f"<table><thead><tr>{heads}</tr></thead>"
                f"<tbody>{rows}</tbody></table></div>"
            )

        blocks.append(
            f'<details class="section{sec_cls}" open><summary>'
            f'<span class="sec-name">{escape(_section_label(labels, stack, section))}</span>'
            f'<span class="sec-stat">{escape(stat)}</span></summary>'
            f"{''.join(sub_html)}</details>"
        )
    return "".join(blocks)


def _render_row(scn: Scenario, show_meta: bool = True) -> str:
    """Render one test-case table row.

    A case with a Gherkin scenario and/or run artifacts renders its description
    as a toggle that expands, in place, to the Given/When/Then plus that exact
    case's screenshots / video / trace from the run being viewed.
    """
    variant = f' <span class="muted">×{scn.variants}</span>' if scn.variants > 1 else ""  # noqa: RUF001
    result_cls = {"passed": "p", "failed": "f", "error": "f", "skipped": "s"}.get(scn.outcome, "n")
    result = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}.get(
        scn.outcome, scn.outcome.upper()
    )
    updated = scn.updated or "uncommitted"
    dur = f"{scn.duration:.2f}s" if scn.duration else "n/a"
    extras = ""
    if scn.gherkin:
        extras += f'<div class="gherkin">{_render_gherkin(scn.gherkin)}</div>'
    if scn.artifacts:
        extras += _render_artifacts(scn.artifacts)
    if extras:
        badge = (
            f' <span class="art-badge">📎 {len(scn.artifacts)}</span>' if scn.artifacts else ""
        )
        desc_cell = (
            f'<button type="button" class="desc-toggle" aria-expanded="false">'
            f'<span class="caret">▸</span>{escape(scn.description)}{variant}{badge}</button>'
            f'<div class="extras" hidden>{extras}</div>'
        )
    else:
        desc_cell = f"{escape(scn.description)}{variant}"
    meta_dots = f'<td class="dots">{_dots(scn.history)}</td>' if show_meta else ""
    meta_updated = f'<td class="num">{escape(updated)}</td>' if show_meta else ""
    return (
        f'<tr class="row {result_cls}-row">'
        f'<td class="desc">{desc_cell}</td>'
        f"{meta_dots}"
        f'<td><span class="pill {result_cls}">{result}</span></td>'
        f'<td class="num">{dur}</td>'
        f"{meta_updated}</tr>"
    )


def _render_artifacts(arts: list[dict[str, str]]) -> str:
    """Render one test case's run artifacts: screenshot thumbnails (click to
    open full size), an inline video player, and download links for the rest
    (e.g. the trace zip, viewable via `npx playwright show-trace`)."""
    thumbs, players, links = [], [], []
    for a in arts:
        path = escape(a.get("path", ""))
        ctype = a.get("contentType", "")
        name = escape(a.get("name", "attachment"))
        if ctype.startswith("image/"):
            thumbs.append(
                f'<a href="{path}" target="_blank" rel="noopener">'
                f'<img src="{path}" alt="{name}" loading="lazy"></a>'
            )
        elif ctype.startswith("video/"):
            players.append(f'<video controls preload="metadata" src="{path}"></video>')
        else:
            links.append(f'<a class="art-link" href="{path}" download>{name}</a>')
    parts = []
    if thumbs:
        parts.append(f'<div class="art-grid">{"".join(thumbs)}</div>')
    if players:
        parts.append(f'<div class="art-videos">{"".join(players)}</div>')
    if links:
        parts.append(f'<div class="art-links">{"".join(links)}</div>')
    return f'<div class="artifacts">{"".join(parts)}</div>'


def _render_gherkin(steps: list[tuple[str, str]]) -> str:
    """Render Given/When/Then step lines, each keyword emphasised."""
    out = []
    for keyword, text in steps:
        out.append(
            f'<div class="step"><span class="kw">{escape(keyword)}</span> {escape(text)}</div>'
        )
    return "".join(out)


_HTML_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sasai Wallet Test Report</title>
<style>
:root {{ color-scheme: dark;
  /* Sasai brand: navy + teal from the official logo, on a dark navy canvas. */
  --navy:#144989; --teal:#48c2cf;
  --pass:#2fbf71; --fail:#f0655a; --skip:#8a9bb0; --none:#24384f;
  --bg:#0a1524; --fg:#e4edf7; --muted:#8fa5bd; --line:#1c3049; --card:#101f34;
  --header:#0d1a2d; --accent:#6fd0dc;
  --shadow:0 1px 2px rgba(0,0,0,.45), 0 12px 32px -16px rgba(0,0,0,.6); }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:14px/1.55 "Avenir Next","Segoe UI",-apple-system,BlinkMacSystemFont,Roboto,sans-serif;
  background:var(--bg); color:var(--fg); }}
.wrap {{ max-width:1240px; margin:0 auto; }}
header {{ padding:18px 28px 14px; position:sticky; top:0; background:var(--header); z-index:5;
  border-bottom:3px solid var(--teal);
  border-image:linear-gradient(90deg, var(--navy) 0%, var(--teal) 70%) 1; }}
.brand {{ display:flex; flex-direction:column; align-items:center; gap:6px; text-align:center; }}
.brand-row {{ display:flex; align-items:center; justify-content:center; gap:16px; }}
.logo-chip {{ background:#fff; border-radius:12px; padding:7px 14px; display:inline-flex;
  align-items:center; }}
.logo-chip img {{ height:30px; width:auto; display:block; }}
h1 {{ font-size:23px; margin:0; letter-spacing:.01em; }}
.sub {{ color:var(--muted); font-size:13px; }}
.controls {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:center;
  padding:18px 0 8px; }}
.tab {{ border:1px solid var(--line); background:var(--card); color:var(--fg); padding:7px 16px;
  border-radius:999px; cursor:pointer; font-size:13px; transition:border-color .15s, background .15s; }}
.tab:hover {{ border-color:var(--teal); }}
.tab.active {{ background:var(--navy); border-color:var(--navy); color:#fff; font-weight:600; }}
.tab.active .muted {{ color:#bfe4f2; }}
.tab .muted {{ font-weight:400; }}
.muted {{ color:var(--muted); }}
label.filter {{ margin-left:12px; color:var(--muted); font-size:13px; cursor:pointer; user-select:none; }}
label.filter input {{ accent-color:var(--navy); }}
.ctl {{ border:1px solid var(--line); background:none; color:var(--muted); padding:5px 12px;
  border-radius:999px; cursor:pointer; font-size:12px; }}
.ctl:hover {{ color:var(--fg); border-color:var(--teal); }}
.fold {{ display:flex; gap:6px; margin-left:12px; }}
main {{ padding:20px 28px 80px; }}
.panel {{ display:none; }} .panel.active {{ display:block; }}
.empty {{ color:var(--muted); }}
details.section {{ border:1px solid var(--line); border-radius:14px; margin:12px 0; overflow:hidden;
  background:var(--card); box-shadow:var(--shadow); }}
details.section > summary {{ list-style:none; cursor:pointer; padding:13px 18px; display:flex;
  align-items:center; gap:12px; }}
details.section > summary:hover .sec-name {{ color:var(--accent); }}
details.section > summary::-webkit-details-marker {{ display:none; }}
.sec-name {{ font-weight:600; font-size:15px; }}
.sec-stat {{ margin-left:auto; color:var(--muted); font-size:12px; }}
.section.has-fail > summary {{ box-shadow:inset 3px 0 0 var(--fail); }}
.sub {{ padding:4px 18px 16px; }}
.sub-head {{ display:flex; gap:10px; align-items:baseline; padding:10px 2px 6px; }}
.sub-file {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; color:var(--accent); }}
.sub-desc {{ color:var(--muted); font-size:12px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.07em;
  color:var(--muted); font-weight:600; padding:6px 10px; border-bottom:1px solid var(--line); }}
td {{ padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
tr.row:hover td {{ background:color-mix(in srgb, var(--teal) 7%, transparent); }}
tr.row:last-child td {{ border-bottom:none; }}
.desc {{ width:52%; }}
.num {{ font-variant-numeric:tabular-nums; color:var(--muted); white-space:nowrap; }}
.dots {{ white-space:nowrap; }}
.dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px;
  background:var(--none); }}
.dot.p {{ background:var(--pass); }} .dot.f {{ background:var(--fail); }} .dot.s {{ background:var(--skip); }}
.pill {{ font-size:11px; font-weight:700; padding:2px 10px; border-radius:999px; }}
.pill.p {{ color:var(--pass); background:color-mix(in srgb, var(--pass) 14%, transparent); }}
.pill.f {{ color:var(--fail); background:color-mix(in srgb, var(--fail) 14%, transparent); }}
.pill.s {{ color:var(--skip); background:color-mix(in srgb, var(--skip) 18%, transparent); }}
body.only-fail tr.p-row, body.only-fail tr.s-row {{ display:none; }}
.desc-toggle {{ display:inline-flex; gap:6px; align-items:baseline; background:none; border:none;
  padding:0; margin:0; font:inherit; color:inherit; text-align:left; cursor:pointer; }}
.desc-toggle:hover {{ color:var(--accent); }}
.caret {{ color:var(--teal); font-size:10px; transition:transform .12s; }}
.desc-toggle[aria-expanded="true"] .caret {{ transform:rotate(90deg); }}
.art-badge {{ font-size:11px; color:var(--accent); }}
.gherkin {{ margin:8px 0 2px; padding:10px 12px; border-left:2px solid var(--teal);
  background:color-mix(in srgb, var(--teal) 6%, transparent); border-radius:0 8px 8px 0; }}
.step {{ font-size:13px; line-height:1.7; }}
.step .kw {{ display:inline-block; min-width:54px; font-weight:700; color:var(--accent); }}
/* Per-test-case run artifacts (E2E) */
.artifacts {{ margin:10px 0 4px; display:flex; flex-direction:column; gap:10px; }}
.art-grid {{ display:flex; gap:10px; flex-wrap:wrap; }}
.art-grid img {{ max-width:280px; max-height:180px; border:1px solid var(--line);
  border-radius:10px; display:block; box-shadow:var(--shadow); }}
.art-grid a:hover img {{ border-color:var(--teal); }}
.art-videos {{ display:flex; gap:10px; flex-wrap:wrap; }}
.art-videos video {{ max-width:480px; width:100%; border:1px solid var(--line); border-radius:10px; }}
.art-links {{ display:flex; gap:12px; }}
.art-link {{ font-size:12px; color:var(--accent); }}
.art-link:hover {{ color:var(--teal); }}
/* E2E run selector */
.run-bar {{ display:flex; gap:10px; align-items:center; margin:4px 0 16px; flex-wrap:wrap; }}
.run-bar label {{ font-weight:600; font-size:13px; }}
.run-bar select {{ border:1px solid var(--line); background:var(--card); color:var(--fg);
  padding:7px 12px; border-radius:10px; font:inherit; font-size:13px; }}
.run-bar select:focus {{ outline:2px solid var(--teal); outline-offset:1px; }}
.run-bar .muted {{ font-size:12px; }}
.e2e-run {{ display:none; }} .e2e-run.active {{ display:block; }}
/* Dashboard tab */
h2 {{ font-size:12px; letter-spacing:.09em; text-transform:uppercase; color:var(--muted);
  margin:30px 0 12px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); gap:14px; }}
.card {{ border:1px solid var(--line); border-radius:16px; padding:18px 20px; background:var(--card);
  box-shadow:var(--shadow); position:relative; overflow:hidden; }}
.card::before {{ content:""; position:absolute; top:0; left:0; width:100%; height:3px;
  background:linear-gradient(90deg, var(--navy), var(--teal)); }}
.card[data-stack] {{ cursor:pointer; transition:transform .12s, border-color .12s; }}
.card[data-stack]:hover {{ border-color:var(--teal); transform:translateY(-1px); }}
.card-title {{ font-size:13px; font-weight:600; display:flex; align-items:center; gap:8px; }}
.card-strip {{ margin-left:auto; }}
.card-rate {{ font-size:28px; font-weight:700; margin:8px 0 10px; font-variant-numeric:tabular-nums;
  color:var(--accent); }}
.card-sub {{ font-size:12px; margin-top:6px; }}
.fail-txt {{ color:var(--fail); font-weight:600; }}
.bar {{ display:flex; height:6px; border-radius:3px; overflow:hidden; background:var(--none); }}
.seg.p {{ background:var(--pass); }} .seg.f {{ background:var(--fail); }} .seg.s {{ background:var(--skip); }}
.all-green {{ color:var(--pass); font-weight:600; }}
.fail-list {{ display:flex; flex-direction:column; gap:6px; }}
.fail-link {{ display:flex; gap:10px; align-items:baseline; width:100%; text-align:left; font:inherit;
  color:inherit; background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:9px 14px; cursor:pointer; box-shadow:var(--shadow); }}
.fail-link:hover {{ border-color:var(--fail); }}
.fail-desc {{ font-weight:500; }}
.fail-link .muted {{ margin-left:auto; font-size:12px; white-space:nowrap; }}
.notes {{ padding-top:12px; }}
.note {{ margin-bottom:14px; }}
.note-title {{ font-weight:600; font-size:13px; margin-bottom:2px; color:var(--accent); }}
.note p {{ margin:0; color:var(--muted); font-size:13px; max-width:820px; }}
.note code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px;
  background:color-mix(in srgb, var(--teal) 12%, transparent); color:var(--accent);
  padding:1px 5px; border-radius:5px; }}
.dash-table td {{ font-size:13px; }}
.dash-table .num {{ white-space:nowrap; }}
.bar-cell {{ width:38%; min-width:140px; vertical-align:middle; }}
</style></head>
<body>
<header><div class="wrap">
  <div class="brand">
    <div class="brand-row">
      <span class="logo-chip"><img src="{logo}" alt="Sasai"></span>
      <h1>Wallet Test Report</h1>
    </div>
    <div class="sub">Automated test cases · generated {generated}</div>
  </div>
</div></header>
<main><div class="wrap">
  <div class="controls">
    {tabs}
    <span class="fold">
      <button type="button" class="ctl" id="expand-all">Expand all</button>
      <button type="button" class="ctl" id="collapse-all">Collapse all</button>
    </span>
    <label class="filter"><input type="checkbox" id="only-fail"> show only failing</label>
  </div>
{panels}</div></main>
<script>
  function activateTab(s) {{
    document.querySelectorAll('.tab').forEach(function (x) {{ x.classList.toggle('active', x.dataset.stack === s); }});
    document.querySelectorAll('.panel').forEach(function (p) {{ p.classList.toggle('active', p.dataset.stack === s); }});
  }}
  document.querySelectorAll('.tab').forEach(function (t) {{
    t.addEventListener('click', function () {{ activateTab(t.dataset.stack); }});
  }});
  // Dashboard failure rows + stack cards jump straight to the owning stack's tab.
  document.querySelectorAll('.fail-link').forEach(function (b) {{
    b.addEventListener('click', function () {{ activateTab(b.dataset.stack); }});
  }});
  document.querySelectorAll('.card[data-stack]').forEach(function (c) {{
    c.addEventListener('click', function () {{ activateTab(c.dataset.stack); }});
    c.addEventListener('keydown', function (e) {{ if (e.key === 'Enter') activateTab(c.dataset.stack); }});
  }});
  // E2E run selector: show exactly one archived run at a time.
  var runSel = document.getElementById('e2e-run-select');
  if (runSel) runSel.addEventListener('change', function () {{
    document.querySelectorAll('.e2e-run').forEach(function (d) {{
      d.classList.toggle('active', d.dataset.run === runSel.value);
    }});
  }});
  // Expand/collapse every section in the ACTIVE tab (dashboard included).
  function setAllOpen(open) {{
    var panel = document.querySelector('.panel.active');
    if (panel) panel.querySelectorAll('details').forEach(function (d) {{ d.open = open; }});
  }}
  document.getElementById('expand-all').addEventListener('click', function () {{ setAllOpen(true); }});
  document.getElementById('collapse-all').addEventListener('click', function () {{ setAllOpen(false); }});
  document.getElementById('only-fail').addEventListener('change', function (e) {{
    document.body.classList.toggle('only-fail', e.target.checked);
  }});
  document.querySelectorAll('.desc-toggle').forEach(function (b) {{
    b.addEventListener('click', function () {{
      var open = b.getAttribute('aria-expanded') === 'true';
      b.setAttribute('aria-expanded', String(!open));
      var panel = b.nextElementSibling;
      if (panel) panel.hidden = open;
    }});
  }});
</script>
</body></html>
"""


def main() -> None:
    """Assemble scenarios, update history + dates, and write the HTML report.

    A stack is "fresh" when its run file exists (a test run just wrote it); those
    outcomes are appended to history once, then the run file is consumed. Stacks
    with no fresh run file are carried forward from the last snapshot, so a
    single-stack run (or a bare re-render) keeps the other tab intact and never
    double-counts. A fresh e2e run is additionally archived (JSON + artifacts)
    under e2e-runs/<stamp>/; the E2E tab always renders from that archive, with
    the newest run doubling as the stack's current state.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    fresh_stacks: set[str] = set()
    if BACKEND_RUN.exists():
        fresh_stacks.add("backend")
    if FRONTEND_RUN.exists():
        fresh_stacks.add("frontend")
    if E2E_RUN.exists():
        fresh_stacks.add("e2e")
        _snapshot_e2e_run()

    # E2E state comes from the newest archived run (artifact paths already
    # rewritten to committed e2e-runs/ files); latest.json is only the fallback
    # for repos that predate the archive.
    e2e_runs = _load_e2e_runs()
    fresh = _collect_backend() + _collect_frontend()
    if e2e_runs:
        fresh += e2e_runs[0][1]
    carried = [
        Scenario(**d)  # type: ignore[arg-type]
        for d in _load_latest()
        if d.get("stack") not in fresh_stacks
        and not (d.get("stack") == "e2e" and e2e_runs)
    ]
    scenarios = fresh + carried

    # Backend descriptions/subsection labels live in the test DOCSTRINGS (source),
    # so re-read them from AST every build — otherwise a carried scenario would
    # show the stale text captured in latest.json at its last run, and docstring
    # edits wouldn't appear until a full re-run.
    _refresh_source_descriptions(scenarios)

    # Attach any matching Gherkin scenario (by "Verify …" name) for the click-to-
    # expand Given/When/Then. Re-derived each build; not persisted in latest.json.
    gherkin = _load_gherkin()
    matched = 0
    for scn in scenarios:
        steps = gherkin.get(_norm(scn.description))
        if steps:
            scn.gherkin = steps
            matched += 1
    # Older archived e2e runs get their Gherkin too (their scenario objects are
    # separate from the main set, which only holds the newest run).
    for _, scns in e2e_runs[1:]:
        for scn in scns:
            scn.gherkin = gherkin.get(_norm(scn.description)) or None

    _apply_history(scenarios, fresh_stacks)
    _apply_dates(scenarios)
    _save_latest(scenarios)
    html = _render(scenarios, e2e_runs)
    # Brand style: no em/en dashes anywhere on the page. Chrome strings avoid
    # them at the source; this net also catches test docstrings and describe
    # titles that carry them in.
    html = html.replace("—", "-").replace("–", "-")
    OUTPUT_PATH.write_text(html, encoding="utf-8")

    # Consume run files so a subsequent re-render doesn't re-append this run.
    for stack, path in (("backend", BACKEND_RUN), ("frontend", FRONTEND_RUN), ("e2e", E2E_RUN)):
        if stack in fresh_stacks:
            path.unlink(missing_ok=True)

    counts = " + ".join(
        f"{sum(1 for s in scenarios if s.stack == stack)} {stack}" for stack in STACKS
    )
    print(f"Report written to {OUTPUT_PATH} ({counts} cases; {matched} with a Gherkin scenario)")


if __name__ == "__main__":
    main()
