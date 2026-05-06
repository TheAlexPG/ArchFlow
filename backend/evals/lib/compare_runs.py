"""Compare current run summary.json vs a baseline, output markdown delta."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def compare(baseline: dict, current: dict) -> str:
    """Returns markdown table of deltas + regression flags.

    Regressions:
      - any score dropped > 10% (vs baseline) → flag.
      - cost increased > 20% → warning.
      - new failures (test in baseline passed, now fails) → flag.
    """
    baseline_items: dict[str, dict] = {
        it["test_id"]: it for it in baseline.get("items", []) if "test_id" in it
    }
    current_items: dict[str, dict] = {
        it["test_id"]: it for it in current.get("items", []) if "test_id" in it
    }

    # Collect all test IDs (union)
    all_ids = sorted(set(baseline_items) | set(current_items))

    regressions: list[str] = []
    rows: list[str] = []

    for test_id in all_ids:
        base = baseline_items.get(test_id)
        curr = current_items.get(test_id)

        if base is None:
            # New test — just report, no regression
            status = curr.get("status", "unknown") if curr else "unknown"
            score = curr.get("score") if curr else None
            score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "—"
            cost = curr.get("cost_usd", 0.0) if curr else 0.0
            rows.append(
                f"| {test_id} | — | {status} | — | {score_str} | — | ${cost:.4f} | ✨ new |"
            )
            continue

        if curr is None:
            # Test removed
            rows.append(f"| {test_id} | {base.get('status', '—')} | — | — | — | — | — | removed |")
            continue

        base_status = base.get("status", "unknown")
        curr_status = curr.get("status", "unknown")
        base_score = base.get("score")
        curr_score = curr.get("score")
        base_cost = float(base.get("cost_usd", 0.0))
        curr_cost = float(curr.get("cost_usd", 0.0))

        flags: list[str] = []

        # New failure: was passing, now failing
        if base_status == "pass" and curr_status != "pass":
            flags.append("🚨 NEW FAILURE")

        # Score regression: dropped > 10%
        if (
            isinstance(base_score, (int, float))
            and isinstance(curr_score, (int, float))
            and base_score > 0
        ):
            drop = (base_score - curr_score) / base_score
            if drop > 0.10:
                flags.append(f"⚠️ score dropped {drop:.0%}")

        # Cost increase > 20%
        if base_cost > 0:
            increase = (curr_cost - base_cost) / base_cost
            if increase > 0.20:
                flags.append(f"💰 cost +{increase:.0%}")

        curr_score_str = f"{curr_score:.3f}" if isinstance(curr_score, (int, float)) else "—"

        # Score delta
        if isinstance(base_score, (int, float)) and isinstance(curr_score, (int, float)):
            delta = curr_score - base_score
            delta_str = f"{delta:+.3f}"
        else:
            delta_str = "—"

        # Cost delta
        cost_delta = curr_cost - base_cost
        cost_delta_str = f"{cost_delta:+.4f}"

        flag_str = " ".join(flags) if flags else "✅ ok"
        row = (
            f"| {test_id} | {base_status} | {curr_status}"
            f" | {delta_str} | {curr_score_str}"
            f" | {cost_delta_str} | ${curr_cost:.4f} | {flag_str} |"
        )
        rows.append(row)
        regressions.extend(flags)

    # Aggregate summary
    base_total = baseline.get("total", 0)
    curr_total = current.get("total", 0)
    base_passed = baseline.get("passed", 0)
    curr_passed = current.get("passed", 0)
    base_cost_total = float(baseline.get("total_cost", 0.0))
    curr_cost_total = float(current.get("total_cost", 0.0))

    lines: list[str] = []
    lines.append("## Eval Run Comparison\n")
    lines.append("### Summary\n")
    lines.append("| Metric | Baseline | Current | Delta |")
    lines.append("|--------|----------|---------|-------|")
    lines.append(
        f"| Total tests | {base_total} | {curr_total} | {curr_total - base_total:+d} |"
    )
    lines.append(
        f"| Passed | {base_passed} | {curr_passed} | {curr_passed - base_passed:+d} |"
    )
    cost_delta_total = curr_cost_total - base_cost_total
    lines.append(
        f"| Total cost | ${base_cost_total:.4f} | ${curr_cost_total:.4f}"
        f" | ${cost_delta_total:+.4f} |"
    )
    lines.append("")

    if regressions:
        lines.append(f"> **{len(regressions)} regression(s) detected.**\n")
    else:
        lines.append("> No regressions detected.\n")

    lines.append("### Per-Test Delta\n")
    lines.append(
        "| Test | Base Status | Curr Status | Score Δ | Curr Score | Cost Δ | Curr Cost | Notes |"
    )
    lines.append(
        "|------|-------------|-------------|---------|------------|--------|-----------|-------|"
    )
    lines.extend(rows)

    return "\n".join(lines)


if __name__ == "__main__":
    baseline = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    current = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    print(compare(baseline, current))
