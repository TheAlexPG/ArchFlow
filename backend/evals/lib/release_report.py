"""Generate index.html + summary.json from per_test/*.json artifacts.

Layout:
  reports/<timestamp>/
    summary.json
    index.html
    per_test/<test_id>.json (input from pytest, generated separately by --json-report or hooks)
    per_test/<test_id>.transcript.md (LLM transcript for debug)
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Use stdlib templating — no Jinja2 dep needed for Phase 1.
# CSS block is kept as a separate constant so its curly braces don't need
# escaping when HTML_TEMPLATE is processed with str.format().
_HTML_CSS = (
    "    body {\n"
    "      font-family: -apple-system, sans-serif;\n"
    "      max-width: 1100px; margin: 1rem auto; padding: 0 1rem;\n"
    "    }\n"
    "    table { width: 100%; border-collapse: collapse; }\n"
    "    th, td { padding: 6px 10px; border-bottom: 1px solid #eee; }\n"
    "    .pass { color: #22c55e; }\n"
    "    .fail { color: #ef4444; }"
)
HTML_TEMPLATE = (
    "<!doctype html>\n<html><head>\n"
    '  <meta charset="utf-8"><title>Agent Evals Report</title>\n'
    "  <style>\n"
    + _HTML_CSS
    + "\n  </style>\n</head><body>\n"
    "  <h1>Agent Evals Report &mdash; {timestamp}</h1>\n"
    "  <p>\n"
    '    Total: {total} | Pass: <span class="pass">{passed}</span>'
    ' | Fail: <span class="fail">{failed}</span>'
    " | Total cost: ${total_cost:.4f}\n"
    "  </p>\n"
    "  <table>\n"
    "    <tr><th>Test</th><th>Status</th>"
    "<th>Score</th><th>Cost</th><th>Time</th></tr>\n"
    "    {rows}\n"
    "  </table>\n"
    "</body></html>"
)


def _render_rows(items: list[dict]) -> str:
    """Render HTML table rows from summary items list."""
    rows: list[str] = []
    for item in items:
        status = item.get("status", "unknown")
        css = "pass" if status == "pass" else "fail"
        score = item.get("score")
        score_str = (
            f"{score:.3f}" if isinstance(score, (int, float)) else str(score or "—")
        )
        cost = item.get("cost_usd", 0.0)
        duration = item.get("duration_s")
        duration_str = (
            f"{duration:.2f}s"
            if isinstance(duration, (int, float))
            else str(duration or "—")
        )
        rows.append(
            f"    <tr>"
            f'<td>{item.get("test_id", "")}</td>'
            f'<td class="{css}">{status}</td>'
            f"<td>{score_str}</td>"
            f"<td>${cost:.4f}</td>"
            f"<td>{duration_str}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def collect_summary(per_test_dir: Path) -> dict:
    """Walk per_test/*.json, aggregate {total, passed, failed, total_cost, items: [...]}."""
    items: list[dict] = []
    for path in sorted(per_test_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            items.append(data)

    passed = sum(1 for it in items if it.get("status") == "pass")
    failed = sum(1 for it in items if it.get("status") != "pass")
    total_cost = sum(float(it.get("cost_usd", 0.0)) for it in items)

    return {
        "total": len(items),
        "passed": passed,
        "failed": failed,
        "total_cost": total_cost,
        "items": items,
    }


def generate(reports_dir: Path) -> Path:
    """Read per_test/*.json from latest run; emit summary.json + index.html.

    Looks for the most-recently modified subdirectory of *reports_dir* that
    contains a ``per_test/`` sub-directory.  If *reports_dir* itself contains
    a ``per_test/`` directory it is used directly.

    Returns path to generated index.html.
    """
    # Resolve the run directory: either reports_dir has per_test/ directly, or
    # we find the latest timestamped sub-directory that has one.
    run_dir: Path | None = None
    if (reports_dir / "per_test").is_dir():
        run_dir = reports_dir
    else:
        candidates = sorted(
            (d for d in reports_dir.iterdir() if d.is_dir() and (d / "per_test").is_dir()),
            key=lambda d: d.stat().st_mtime,
        )
        if candidates:
            run_dir = candidates[-1]

    if run_dir is None:
        raise FileNotFoundError(
            f"No run directory with a per_test/ sub-directory found under {reports_dir}"
        )

    summary = collect_summary(run_dir / "per_test")
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # Write summary.json
    summary_path = run_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    # Write index.html — use manual replacement to avoid conflict between
    # CSS curly braces in the template and str.format() placeholder syntax.
    rows_html = _render_rows(summary["items"])
    html = (
        HTML_TEMPLATE
        .replace("{timestamp}", timestamp)
        .replace("{total}", str(summary["total"]))
        .replace("{passed}", str(summary["passed"]))
        .replace("{failed}", str(summary["failed"]))
        .replace("{total_cost:.4f}", f"{summary['total_cost']:.4f}")
        .replace("{rows}", rows_html)
    )
    html_path = run_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")

    return html_path


if __name__ == "__main__":
    reports_root = Path(sys.argv[1] if len(sys.argv) > 1 else "reports")
    out = generate(reports_root)
    print(f"Wrote {out}")
