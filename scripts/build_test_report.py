"""Build the combined Sasai test report (HTML) from backend + frontend runs.

Joins raw per-test outcomes (pytest via the conftest recorder → backend-run.json;
vitest --reporter=json → frontend-run.json) with:

  * the test's human description (Python: function docstring 1st line via AST;
    frontend: the `it(...)` title),
  * its SECTION (backend: test dir; frontend: top `describe`) and SUBSECTION
    (the test file, labelled by its module docstring / basename),
  * a rolling PASS/FAIL history of the last 3 report builds (test-reports/history.json),
  * a "last updated" date read from git — per test FUNCTION for the backend
    (exact AST line-span → `git log -L`), per FILE for the frontend.

Emits test-reports/index.html (one page, Backend / Frontend tabs). Run via
`make report` (both stacks) or the per-stack make targets. Idempotent; safe to
re-run. Pure reporting — never touches application code or the databases.
"""
# ruff: noqa: E501 — the embedded HTML/CSS/JS template (_HTML_SHELL) has long
# lines that are clearer left unwrapped; line-length isn't meaningful here.

from __future__ import annotations

import ast
import json
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

    stack: str  # "backend" | "frontend"
    section: str  # slug (backend dir) / top describe title (frontend)
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


def _labels() -> dict[str, dict[str, str]]:
    """Load the friendly section-label registry (empty-safe)."""
    data = _load_json(LABELS_PATH)
    return data if isinstance(data, dict) else {}


def _section_label(labels: dict[str, dict[str, str]], stack: str, slug: str) -> str:
    """Friendly section name.

    Backend sections are dir slugs → mapped to a friendly label (else title-cased).
    Frontend sections are `describe(...)` titles — already prose — so they render
    verbatim when unmapped, never title-cased.
    """
    mapped = labels.get(stack, {}).get(slug)
    if mapped:
        return mapped
    return slug if stack == "frontend" else _humanise(slug)


def _dots(history: list[dict[str, str]]) -> str:
    """Render the last-3 pass/fail strip (oldest→newest, left-padded)."""
    slots = [None] * (HISTORY_LIMIT - len(history)) + [h.get("outcome") for h in history]
    out = []
    for slot in slots[-HISTORY_LIMIT:]:
        cls = {"passed": "p", "failed": "f", "error": "f", "skipped": "s"}.get(slot or "", "n")
        title = slot or "not run"
        out.append(f'<span class="dot {cls}" title="{escape(title)}"></span>')
    return "".join(out)


def _render(scenarios: list[Scenario]) -> str:
    """Render the full self-contained HTML page."""
    labels = _labels()
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    stacks: dict[str, list[Scenario]] = {"backend": [], "frontend": []}
    for scn in scenarios:
        stacks.setdefault(scn.stack, []).append(scn)

    tabs, panels = [], []
    for stack in ("backend", "frontend"):
        items = stacks.get(stack, [])
        passed = sum(1 for s in items if s.outcome == "passed")
        failed = sum(1 for s in items if s.outcome in ("failed", "error"))
        total = len(items)
        active = " active" if stack == "backend" else ""
        badge = f"{passed}/{total} ✓" + (f" · {failed} ✗" if failed else "")
        tabs.append(
            f'<button class="tab{active}" data-stack="{stack}">'
            f'{stack.capitalize()} <span class="muted">{escape(badge)}</span></button>'
        )
        panels.append(
            f'<div class="panel{active}" data-stack="{stack}">{_render_stack(stack, items, labels)}</div>'
        )

    return _HTML_SHELL.format(
        generated=escape(generated),
        tabs="".join(tabs),
        panels="".join(panels),
    )


def _render_stack(stack: str, items: list[Scenario], labels: dict[str, dict[str, str]]) -> str:
    """Render one stack's collapsible sections → subsections → case rows."""
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
                _render_row(s) for s in sorted(subs, key=lambda s: s.description.lower())
            )
            # Backend: show the file + its module-docstring (a section spans many
            # files). Frontend: each section IS one file, so a filename header
            # would just repeat noise — skip it and show the cases directly.
            head = (
                ""
                if stack == "frontend"
                else f'<div class="sub-head" title="{escape(rel_path)}">'
                f'<span class="sub-file">{escape(Path(rel_path).name)}</span>'
                f'<span class="sub-desc">{escape(label)}</span></div>'
            )
            sub_html.append(
                f'<div class="sub">{head}'
                f"<table><thead><tr><th>Test case</th><th>Last 3 runs</th>"
                f"<th>Latest</th><th>Time</th><th>Updated</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>"
            )

        blocks.append(
            f'<details class="section{sec_cls}" open><summary>'
            f'<span class="sec-name">{escape(_section_label(labels, stack, section))}</span>'
            f'<span class="sec-stat">{escape(stat)}</span></summary>'
            f"{''.join(sub_html)}</details>"
        )
    return "".join(blocks)


def _render_row(scn: Scenario) -> str:
    """Render one test-case table row."""
    variant = f' <span class="muted">×{scn.variants}</span>' if scn.variants > 1 else ""  # noqa: RUF001
    result_cls = {"passed": "p", "failed": "f", "error": "f", "skipped": "s"}.get(scn.outcome, "n")
    result = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "skipped": "SKIP"}.get(
        scn.outcome, scn.outcome.upper()
    )
    updated = scn.updated or "uncommitted"
    dur = f"{scn.duration:.2f}s" if scn.duration else "—"
    # When a matching .feature Scenario exists, the description becomes a toggle
    # that reveals its Given/When/Then; otherwise it's plain text.
    if scn.gherkin:
        desc_cell = (
            f'<button type="button" class="desc-toggle" aria-expanded="false">'
            f'<span class="caret">▸</span>{escape(scn.description)}{variant}</button>'
            f'<div class="gherkin" hidden>{_render_gherkin(scn.gherkin)}</div>'
        )
    else:
        desc_cell = f"{escape(scn.description)}{variant}"
    return (
        f'<tr class="row {result_cls}-row">'
        f'<td class="desc">{desc_cell}</td>'
        f'<td class="dots">{_dots(scn.history)}</td>'
        f'<td><span class="pill {result_cls}">{result}</span></td>'
        f'<td class="num">{dur}</td>'
        f'<td class="num">{escape(updated)}</td></tr>'
    )


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
<title>Sasai Test Report</title>
<style>
:root {{ color-scheme: light dark; --pass:#16a34a; --fail:#dc2626; --skip:#9ca3af; --none:#d1d5db;
  --bg:#ffffff; --fg:#111827; --muted:#6b7280; --line:#e5e7eb; --card:#f9fafb; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b0f17; --fg:#e5e7eb; --muted:#9ca3af;
  --line:#1f2937; --card:#111827; --none:#374151; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg); color:var(--fg); }}
header {{ padding:20px 24px; border-bottom:1px solid var(--line); position:sticky; top:0;
  background:var(--bg); z-index:5; }}
h1 {{ font-size:18px; margin:0 0 4px; }}
.gen {{ color:var(--muted); font-size:12px; }}
.controls {{ margin-top:14px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
.tab {{ border:1px solid var(--line); background:var(--card); color:var(--fg); padding:6px 14px;
  border-radius:8px; cursor:pointer; font-size:13px; }}
.tab.active {{ border-color:var(--fg); font-weight:600; }}
.tab .muted {{ font-weight:400; }}
.muted {{ color:var(--muted); }}
label.filter {{ margin-left:auto; color:var(--muted); font-size:13px; cursor:pointer; user-select:none; }}
main {{ padding:16px 24px 60px; }}
.panel {{ display:none; }} .panel.active {{ display:block; }}
.empty {{ color:var(--muted); }}
details.section {{ border:1px solid var(--line); border-radius:10px; margin:10px 0; overflow:hidden; }}
details.section > summary {{ list-style:none; cursor:pointer; padding:12px 16px; display:flex;
  align-items:center; gap:12px; background:var(--card); }}
details.section > summary::-webkit-details-marker {{ display:none; }}
.sec-name {{ font-weight:600; font-size:15px; }}
.sec-stat {{ margin-left:auto; color:var(--muted); font-size:12px; }}
.section.has-fail > summary {{ box-shadow:inset 3px 0 0 var(--fail); }}
.sub {{ padding:4px 16px 14px; }}
.sub-head {{ display:flex; gap:10px; align-items:baseline; padding:10px 2px 6px; }}
.sub-file {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }}
.sub-desc {{ color:var(--muted); font-size:12px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); font-weight:600; padding:6px 8px; border-bottom:1px solid var(--line); }}
td {{ padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
tr.row:last-child td {{ border-bottom:none; }}
.desc {{ width:52%; }}
.num {{ font-variant-numeric:tabular-nums; color:var(--muted); white-space:nowrap; }}
.dots {{ white-space:nowrap; }}
.dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px;
  background:var(--none); }}
.dot.p {{ background:var(--pass); }} .dot.f {{ background:var(--fail); }} .dot.s {{ background:var(--skip); }}
.pill {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; }}
.pill.p {{ color:var(--pass); background:color-mix(in srgb, var(--pass) 15%, transparent); }}
.pill.f {{ color:var(--fail); background:color-mix(in srgb, var(--fail) 15%, transparent); }}
.pill.s {{ color:var(--skip); background:color-mix(in srgb, var(--skip) 18%, transparent); }}
body.only-fail tr.p-row, body.only-fail tr.s-row {{ display:none; }}
.desc-toggle {{ display:inline-flex; gap:6px; align-items:baseline; background:none; border:none;
  padding:0; margin:0; font:inherit; color:inherit; text-align:left; cursor:pointer; }}
.desc-toggle:hover {{ color:var(--fg); }}
.caret {{ color:var(--muted); font-size:10px; transition:transform .12s; }}
.desc-toggle[aria-expanded="true"] .caret {{ transform:rotate(90deg); }}
.gherkin {{ margin:8px 0 2px; padding:10px 12px; border-left:2px solid var(--line);
  background:var(--card); border-radius:0 6px 6px 0; }}
.step {{ font-size:13px; line-height:1.7; }}
.step .kw {{ display:inline-block; min-width:54px; font-weight:700; color:var(--muted); }}
</style></head>
<body>
<header>
  <h1>Sasai Wallet — Test Report</h1>
  <div class="gen">Generated {generated}</div>
  <div class="controls">
    {tabs}
    <label class="filter"><input type="checkbox" id="only-fail"> show only failing</label>
  </div>
</header>
<main>{panels}</main>
<script>
  document.querySelectorAll('.tab').forEach(function (t) {{
    t.addEventListener('click', function () {{
      var s = t.dataset.stack;
      document.querySelectorAll('.tab').forEach(function (x) {{ x.classList.toggle('active', x === t); }});
      document.querySelectorAll('.panel').forEach(function (p) {{ p.classList.toggle('active', p.dataset.stack === s); }});
    }});
  }});
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
    double-counts.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    fresh_stacks: set[str] = set()
    if BACKEND_RUN.exists():
        fresh_stacks.add("backend")
    if FRONTEND_RUN.exists():
        fresh_stacks.add("frontend")

    fresh = _collect_backend() + _collect_frontend()
    carried = [
        Scenario(**d)  # type: ignore[arg-type]
        for d in _load_latest()
        if d.get("stack") not in fresh_stacks
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

    _apply_history(scenarios, fresh_stacks)
    _apply_dates(scenarios)
    _save_latest(scenarios)
    OUTPUT_PATH.write_text(_render(scenarios), encoding="utf-8")

    # Consume run files so a subsequent re-render doesn't re-append this run.
    for stack, path in (("backend", BACKEND_RUN), ("frontend", FRONTEND_RUN)):
        if stack in fresh_stacks:
            path.unlink(missing_ok=True)

    b = sum(1 for s in scenarios if s.stack == "backend")
    f = sum(1 for s in scenarios if s.stack == "frontend")
    print(
        f"Report written to {OUTPUT_PATH} ({b} backend + {f} frontend cases; "
        f"{matched} with a Gherkin scenario)"
    )


if __name__ == "__main__":
    main()
