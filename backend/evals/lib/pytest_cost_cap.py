"""Pytest plugin: enforces ``--cost-cap`` during eval runs.

Each test that touches an LLM is expected to use the ``record_cost`` fixture
(see ``evals/conftest.py``). The fixture appends per-call dollar amounts; on
teardown it stores the test's total under
``user_properties[("cost_usd", float)]``. After the whole run we sum those
totals and, if ``--cost-cap=$X`` was passed, fail the run when ``total > X``.

Also exposes:

* ``--smoke``: keep only the first parametrize ID per test function. Used by
  ``make eval-quick`` to get a fast-but-representative pass.
* ``--cost-cap-disable``: explicit escape hatch (e.g. local exploration with a
  paid model where you accept the spend).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("evals", "Agent evals options")
    group.addoption(
        "--cost-cap",
        type=float,
        default=None,
        help="Max $ cost for the run (sum of per-test cost_usd).",
    )
    group.addoption(
        "--smoke",
        action="store_true",
        default=False,
        help="Smoke mode: keep only the first parametrize case per test.",
    )
    group.addoption(
        "--cost-cap-disable",
        action="store_true",
        default=False,
        help="Disable cost-cap enforcement even if --cost-cap is supplied.",
    )


# ---------------------------------------------------------------------------
# Smoke filter
# ---------------------------------------------------------------------------


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """When ``--smoke`` is set, keep only the first parametrize case per test.

    A test function may live in multiple categories (parametrize IDs). For a
    smoke pass we want one representative case per ``test_<name>`` so the run
    finishes in seconds instead of minutes.
    """
    if not config.getoption("--smoke"):
        return

    seen: dict[str, int] = defaultdict(int)
    deselected: list[pytest.Item] = []
    kept: list[pytest.Item] = []
    for item in items:
        # ``nodeid`` looks like ``path::TestClass::test_name[param-id]``.
        # Strip the ``[...]`` suffix to group parametrize variants together.
        base = item.nodeid.split("[", 1)[0]
        if seen[base] >= 1:
            deselected.append(item)
        else:
            seen[base] += 1
            kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


# ---------------------------------------------------------------------------
# Cost cap enforcement
# ---------------------------------------------------------------------------


def _sum_cost(reports: list[Any]) -> float:
    """Sum every ``("cost_usd", float)`` user_property across reports."""
    total = 0.0
    for report in reports:
        for key, value in getattr(report, "user_properties", []) or []:
            if key == "cost_usd":
                try:
                    total += float(value)
                except (TypeError, ValueError):
                    continue
    return total


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config
) -> None:
    """Sum costs from ``user_properties`` and warn / fail when the cap is hit."""
    cap = config.getoption("--cost-cap")
    disabled = config.getoption("--cost-cap-disable")

    # Aggregate across pass/fail/skip outcomes — a failed test still spent $.
    reports: list[Any] = []
    for outcome in ("passed", "failed", "error"):
        reports.extend(terminalreporter.stats.get(outcome, []))

    total = _sum_cost(reports)
    if total <= 0 and cap is None:
        return

    terminalreporter.section("evals: cost summary")
    terminalreporter.write_line(f"total cost recorded: ${total:.4f}")

    if cap is None or disabled:
        if disabled:
            terminalreporter.write_line("cost-cap enforcement disabled (--cost-cap-disable)")
        return

    terminalreporter.write_line(f"cost cap: ${cap:.4f}")
    if total > cap:
        terminalreporter.write_line(
            f"COST CAP EXCEEDED: ${total:.4f} > ${cap:.4f}",
            red=True,
            bold=True,
        )
        # Mutate the session result so CI fails. Pytest doesn't expose a
        # clean "fail the run from terminal_summary" hook, so we set the
        # exitcode on the session via the terminalreporter.
        session = getattr(terminalreporter, "_session", None)
        if session is not None:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        # Raise UsageError-style line so it's visible even without -ra.
        terminalreporter._tw.line("evals: failing run due to cost overage", red=True)
    else:
        terminalreporter.write_line("cost cap OK", green=True)
