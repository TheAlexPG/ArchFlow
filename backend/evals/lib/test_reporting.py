"""Tests for eval reporting: release_report, compare_runs, baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.lib.baseline import save_baseline
from evals.lib.compare_runs import compare
from evals.lib.release_report import collect_summary, generate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_per_test(tmp_path: Path, items: list[dict]) -> Path:
    """Write synthetic per_test/*.json files into tmp_path/per_test/."""
    per_test = tmp_path / "per_test"
    per_test.mkdir(parents=True, exist_ok=True)
    for item in items:
        (per_test / f"{item['test_id']}.json").write_text(
            json.dumps(item), encoding="utf-8"
        )
    return tmp_path


_SAMPLE_ITEMS = [
    {"test_id": "test_a", "status": "pass", "score": 0.9, "cost_usd": 0.01, "duration_s": 1.2},
    {"test_id": "test_b", "status": "pass", "score": 0.8, "cost_usd": 0.02, "duration_s": 2.1},
    {"test_id": "test_c", "status": "fail", "score": 0.3, "cost_usd": 0.005, "duration_s": 0.8},
]


# ---------------------------------------------------------------------------
# collect_summary
# ---------------------------------------------------------------------------


def test_collect_summary_aggregates_correctly(tmp_path: Path) -> None:
    """collect_summary counts pass/fail and sums cost from per_test/*.json."""
    run_dir = _make_per_test(tmp_path, _SAMPLE_ITEMS)
    summary = collect_summary(run_dir / "per_test")

    assert summary["total"] == 3
    assert summary["passed"] == 2
    assert summary["failed"] == 1
    assert summary["total_cost"] == pytest.approx(0.035)
    assert len(summary["items"]) == 3


def test_collect_summary_empty_dir(tmp_path: Path) -> None:
    """collect_summary on an empty directory returns zero counts."""
    per_test = tmp_path / "per_test"
    per_test.mkdir()
    summary = collect_summary(per_test)

    assert summary["total"] == 0
    assert summary["passed"] == 0
    assert summary["failed"] == 0
    assert summary["total_cost"] == 0.0
    assert summary["items"] == []


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def test_generate_writes_html_and_summary_json(tmp_path: Path) -> None:
    """generate() writes index.html + summary.json into the run directory."""
    _make_per_test(tmp_path / "run1", _SAMPLE_ITEMS)

    html_path = generate(tmp_path / "run1")

    assert html_path.name == "index.html"
    assert html_path.is_file()

    summary_path = tmp_path / "run1" / "summary.json"
    assert summary_path.is_file()

    summary = json.loads(summary_path.read_text())
    assert summary["total"] == 3
    assert summary["passed"] == 2
    assert summary["failed"] == 1

    html = html_path.read_text(encoding="utf-8")
    assert "Agent Evals Report" in html
    assert "test_a" in html
    assert "test_b" in html
    assert "test_c" in html
    # Pass/fail CSS classes present
    assert 'class="pass"' in html
    assert 'class="fail"' in html


def test_generate_uses_latest_subdirectory(tmp_path: Path) -> None:
    """generate() picks the most-recently modified sub-directory with per_test/."""
    reports = tmp_path / "reports"
    reports.mkdir()

    # Create two timestamped run dirs
    run_old = reports / "2026-01-01"
    _make_per_test(run_old, [{"test_id": "t_old", "status": "pass", "cost_usd": 0.0}])

    run_new = reports / "2026-04-27"
    _make_per_test(
        run_new,
        [{"test_id": "t_new", "status": "pass", "cost_usd": 0.0}],
    )
    # Touch run_new to ensure it's newer
    (run_new / "per_test" / "t_new.json").touch()

    html_path = generate(reports)
    assert html_path.parent == run_new
    html = html_path.read_text(encoding="utf-8")
    assert "t_new" in html


def test_generate_raises_when_no_per_test_dir(tmp_path: Path) -> None:
    """generate() raises FileNotFoundError if no per_test/ directory exists."""
    (tmp_path / "empty_run").mkdir()
    with pytest.raises(FileNotFoundError):
        generate(tmp_path)


# ---------------------------------------------------------------------------
# compare: no regressions
# ---------------------------------------------------------------------------


def _make_summary(items: list[dict]) -> dict:
    passed = sum(1 for it in items if it.get("status") == "pass")
    failed = len(items) - passed
    total_cost = sum(float(it.get("cost_usd", 0.0)) for it in items)
    return {
        "total": len(items),
        "passed": passed,
        "failed": failed,
        "total_cost": total_cost,
        "items": items,
    }


def test_compare_same_vs_same_no_regressions() -> None:
    """Comparing a run against itself yields no regression flags."""
    summary = _make_summary(
        [
            {"test_id": "t1", "status": "pass", "score": 0.9, "cost_usd": 0.01},
            {"test_id": "t2", "status": "pass", "score": 0.8, "cost_usd": 0.02},
        ]
    )
    result = compare(summary, summary)
    assert "No regressions detected" in result
    assert "NEW FAILURE" not in result
    assert "score dropped" not in result
    assert "cost +" not in result


# ---------------------------------------------------------------------------
# compare: score drop > 10%
# ---------------------------------------------------------------------------


def test_compare_score_drop_flagged() -> None:
    """A score drop > 10% is flagged as a regression."""
    baseline = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 1.0, "cost_usd": 0.01}]
    )
    current = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 0.8, "cost_usd": 0.01}]
    )
    result = compare(baseline, current)
    assert "score dropped" in result
    assert "regression(s) detected" in result


def test_compare_score_drop_within_threshold_not_flagged() -> None:
    """A score drop of exactly 10% (not exceeding) is not flagged."""
    baseline = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 1.0, "cost_usd": 0.01}]
    )
    current = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 0.90, "cost_usd": 0.01}]
    )
    result = compare(baseline, current)
    assert "score dropped" not in result


# ---------------------------------------------------------------------------
# compare: cost increased > 20%
# ---------------------------------------------------------------------------


def test_compare_cost_increase_flagged() -> None:
    """A cost increase > 20% emits a cost warning."""
    baseline = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 0.9, "cost_usd": 0.10}]
    )
    current = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 0.9, "cost_usd": 0.13}]
    )
    result = compare(baseline, current)
    assert "cost +" in result
    assert "regression(s) detected" in result


def test_compare_cost_increase_within_threshold_ok() -> None:
    """A cost increase of exactly 20% (not exceeding) is not flagged."""
    baseline = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 0.9, "cost_usd": 0.10}]
    )
    current = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 0.9, "cost_usd": 0.12}]
    )
    result = compare(baseline, current)
    assert "cost +" not in result


# ---------------------------------------------------------------------------
# compare: new failure
# ---------------------------------------------------------------------------


def test_compare_new_failure_flagged() -> None:
    """A test that passed in baseline but fails now is flagged as NEW FAILURE."""
    baseline = _make_summary(
        [{"test_id": "t1", "status": "pass", "score": 0.9, "cost_usd": 0.01}]
    )
    current = _make_summary(
        [{"test_id": "t1", "status": "fail", "score": 0.2, "cost_usd": 0.01}]
    )
    result = compare(baseline, current)
    assert "NEW FAILURE" in result
    assert "regression(s) detected" in result


# ---------------------------------------------------------------------------
# save_baseline
# ---------------------------------------------------------------------------


def test_save_baseline_creates_dated_file(tmp_path: Path) -> None:
    """save_baseline copies summary.json with today's date as the default tag."""
    reports = tmp_path / "reports" / "run1"
    reports.mkdir(parents=True)
    summary = _make_summary(_SAMPLE_ITEMS)
    (reports / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    baselines_dir = tmp_path / "baselines"
    dest = save_baseline(tmp_path / "reports", baselines_dir)

    assert dest.is_file()
    # Default tag is today's date YYYY-MM-DD
    assert dest.suffix == ".json"
    import re

    assert re.match(r"\d{4}-\d{2}-\d{2}\.json", dest.name)

    saved = json.loads(dest.read_text())
    assert saved["total"] == summary["total"]


def test_save_baseline_custom_tag(tmp_path: Path) -> None:
    """save_baseline uses the supplied tag when given."""
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "summary.json").write_text(
        json.dumps(_make_summary(_SAMPLE_ITEMS)), encoding="utf-8"
    )

    baselines_dir = tmp_path / "baselines"
    dest = save_baseline(reports, baselines_dir, tag="v1.0.0")

    assert dest.name == "v1.0.0.json"
    assert dest.is_file()


def test_save_baseline_raises_when_no_summary(tmp_path: Path) -> None:
    """save_baseline raises FileNotFoundError when no summary.json exists."""
    with pytest.raises(FileNotFoundError):
        save_baseline(tmp_path / "empty_reports", tmp_path / "baselines")
