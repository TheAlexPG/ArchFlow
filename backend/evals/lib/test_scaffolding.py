"""Tests for the eval scaffolding itself.

These tests do **not** make real LLM calls — they exercise plumbing only:
the judge wrapper's identity methods, the golden loader, the cost-cap
plugin's smoke filter and overage detection, and conftest fixture
importability. Real-LLM eval tests live in tasks 057–059.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.lib.judge import DeepEvalLitellmWrapper
from evals.lib.pytest_cost_cap import (
    _sum_cost,
    pytest_collection_modifyitems,
    pytest_terminal_summary,
)

# ---------------------------------------------------------------------------
# Judge wrapper
# ---------------------------------------------------------------------------


def test_judge_wrapper_identity_methods() -> None:
    """get_model_name / load_model expose the configured model without calls."""
    wrapper = DeepEvalLitellmWrapper(
        model="openai/gpt-4o-mini",
        api_key="sk-fake",
        base_url="https://example.invalid/v1",
    )
    assert wrapper.get_model_name() == "openai/gpt-4o-mini"
    # ``load_model`` should return the wrapper itself (DeepEval pattern).
    assert wrapper.load_model() is wrapper


# ---------------------------------------------------------------------------
# Golden loader
# ---------------------------------------------------------------------------


def test_load_golden_loads_and_filters_by_category(tmp_path: Path) -> None:
    """``load_golden`` returns the full list and supports a category filter."""
    # Import lazily so the conftest module is loaded inside the test (it has a
    # session-scoped fixture that pulls in the agent imports — fine here
    # because pytest already collected the tree).
    from evals.conftest import load_golden

    # Stage a temp golden file inside the canonical golden/ directory by
    # writing into the real evals/golden/ tree under a unique name. We keep
    # the file ASCII-small and remove it on teardown via tmp_path-managed
    # cleanup pattern: write to evals/golden then unlink in finally.
    golden_dir = Path(__file__).resolve().parents[1] / "golden"
    test_file = golden_dir / "_scaffolding_fixture.json"
    payload = [
        {"id": "a", "category": "alpha", "prompt": "p1"},
        {"id": "b", "category": "beta", "prompt": "p2"},
        {"id": "c", "prompt": "p3"},  # missing category
    ]
    test_file.write_text(json.dumps(payload), encoding="utf-8")
    try:
        all_entries = load_golden("_scaffolding_fixture.json")
        assert len(all_entries) == 3

        only_alpha = load_golden("_scaffolding_fixture.json", category="alpha")
        assert [e["id"] for e in only_alpha] == ["a"]

        # Missing-category entries are dropped when a filter is supplied.
        only_beta = load_golden("_scaffolding_fixture.json", category="beta")
        assert [e["id"] for e in only_beta] == ["b"]
    finally:
        test_file.unlink(missing_ok=True)


def test_load_golden_handles_empty_placeholder() -> None:
    """The shipped placeholder JSONs (empty arrays) parse to empty lists."""
    from evals.conftest import load_golden

    assert load_golden("planner.json") == []


# ---------------------------------------------------------------------------
# pytest_cost_cap: --smoke filter
# ---------------------------------------------------------------------------


class _FakeItem:
    """Minimal stand-in for ``pytest.Item`` (only ``nodeid`` is read)."""

    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid


class _FakeHook:
    def __init__(self) -> None:
        self.deselected: list[Any] = []

    def pytest_deselected(self, items: list[Any]) -> None:
        self.deselected.extend(items)


class _FakeConfig:
    def __init__(self, *, smoke: bool) -> None:
        self._smoke = smoke
        self.hook = _FakeHook()

    def getoption(self, name: str) -> Any:
        if name == "--smoke":
            return self._smoke
        raise KeyError(name)


def test_smoke_filter_keeps_one_case_per_test() -> None:
    """``--smoke`` deselects every parametrize variant past the first."""
    items = [
        _FakeItem("evals/test_planner.py::test_basic[case-a]"),
        _FakeItem("evals/test_planner.py::test_basic[case-b]"),
        _FakeItem("evals/test_planner.py::test_basic[case-c]"),
        _FakeItem("evals/test_planner.py::test_other"),
        _FakeItem("evals/test_critic.py::test_x[only]"),
    ]
    config = _FakeConfig(smoke=True)
    pytest_collection_modifyitems(config, items)  # type: ignore[arg-type]

    kept_ids = [it.nodeid for it in items]
    assert kept_ids == [
        "evals/test_planner.py::test_basic[case-a]",
        "evals/test_planner.py::test_other",
        "evals/test_critic.py::test_x[only]",
    ]
    deselected_ids = [it.nodeid for it in config.hook.deselected]
    assert deselected_ids == [
        "evals/test_planner.py::test_basic[case-b]",
        "evals/test_planner.py::test_basic[case-c]",
    ]


def test_smoke_filter_noop_when_disabled() -> None:
    """Without ``--smoke`` the items list is left untouched."""
    items = [
        _FakeItem("evals/test_planner.py::test_basic[case-a]"),
        _FakeItem("evals/test_planner.py::test_basic[case-b]"),
    ]
    config = _FakeConfig(smoke=False)
    pytest_collection_modifyitems(config, items)  # type: ignore[arg-type]
    assert [it.nodeid for it in items] == [
        "evals/test_planner.py::test_basic[case-a]",
        "evals/test_planner.py::test_basic[case-b]",
    ]
    assert config.hook.deselected == []


# ---------------------------------------------------------------------------
# pytest_cost_cap: total cost > cap -> warning + non-zero exit
# ---------------------------------------------------------------------------


class _FakeReport:
    def __init__(self, costs: list[float]) -> None:
        self.user_properties = [("cost_usd", c) for c in costs]


class _FakeTW:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def line(self, msg: str, **kwargs: Any) -> None:
        self.lines.append(msg)


class _FakeTerminalReporter:
    def __init__(self, reports: dict[str, list[_FakeReport]]) -> None:
        self.stats = reports
        self.lines: list[str] = []
        self.sections: list[str] = []
        self._tw = _FakeTW()
        self._session = SimpleNamespace(exitstatus=0)

    def section(self, title: str) -> None:
        self.sections.append(title)

    def write_line(self, msg: str, **kwargs: Any) -> None:
        self.lines.append(msg)


class _CapConfig:
    def __init__(self, *, cap: float | None, disabled: bool = False) -> None:
        self._cap = cap
        self._disabled = disabled

    def getoption(self, name: str) -> Any:
        if name == "--cost-cap":
            return self._cap
        if name == "--cost-cap-disable":
            return self._disabled
        raise KeyError(name)


def test_sum_cost_aggregates_user_properties() -> None:
    reports = [_FakeReport([0.1, 0.05]), _FakeReport([0.2])]
    assert _sum_cost(reports) == pytest.approx(0.35)


def test_terminal_summary_fails_when_total_exceeds_cap() -> None:
    """Total > cap → warning emitted + session exitstatus flipped to failed."""
    reporter = _FakeTerminalReporter(
        {"passed": [_FakeReport([0.30, 0.25]), _FakeReport([0.10])]}
    )
    config = _CapConfig(cap=0.50)

    pytest_terminal_summary(reporter, exitstatus=0, config=config)  # type: ignore[arg-type]

    summary = "\n".join(reporter.lines + reporter._tw.lines)
    assert "total cost recorded" in summary
    assert "COST CAP EXCEEDED" in summary
    assert reporter._session.exitstatus == pytest.ExitCode.TESTS_FAILED


def test_terminal_summary_ok_when_under_cap() -> None:
    """Total ≤ cap → ``cost cap OK`` emitted, exitstatus untouched."""
    reporter = _FakeTerminalReporter({"passed": [_FakeReport([0.10])]})
    config = _CapConfig(cap=0.50)

    pytest_terminal_summary(reporter, exitstatus=0, config=config)  # type: ignore[arg-type]

    assert any("cost cap OK" in line for line in reporter.lines)
    assert reporter._session.exitstatus == 0


def test_terminal_summary_disabled_skips_enforcement() -> None:
    """``--cost-cap-disable`` short-circuits even on overage."""
    reporter = _FakeTerminalReporter({"passed": [_FakeReport([5.0])]})
    config = _CapConfig(cap=0.50, disabled=True)

    pytest_terminal_summary(reporter, exitstatus=0, config=config)  # type: ignore[arg-type]

    assert reporter._session.exitstatus == 0
    assert not any("COST CAP EXCEEDED" in line for line in reporter.lines)


# ---------------------------------------------------------------------------
# Conftest fixtures importability
# ---------------------------------------------------------------------------


def test_conftest_module_importable() -> None:
    """Conftest imports cleanly and exposes the documented surface."""
    import evals.conftest as conftest

    # Public helpers + fixtures.
    assert callable(conftest.load_golden)
    assert hasattr(conftest, "eval_model")
    assert hasattr(conftest, "record_cost")
    assert hasattr(conftest, "run_node")
    assert hasattr(conftest, "run_full_pipeline")

    # Plugin registration.
    assert "evals.lib.pytest_cost_cap" in conftest.pytest_plugins


def test_eval_model_fixture_returns_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    """``eval_model`` materialises a DeepEvalLitellmWrapper for the env model."""
    monkeypatch.setenv("EVAL_MODEL", "openai/gpt-4o-mini")
    monkeypatch.delenv("EVAL_LLM_KEY", raising=False)
    monkeypatch.delenv("EVAL_LLM_BASE_URL", raising=False)

    # Call the underlying function directly — pytest fixtures are wrappers
    # around the original callable accessible via ``__wrapped__``.
    from evals.conftest import eval_model

    fn = getattr(eval_model, "__wrapped__", eval_model)
    instance = fn()
    assert isinstance(instance, DeepEvalLitellmWrapper)
    assert instance.get_model_name() == "openai/gpt-4o-mini"


def test_record_cost_fixture_records_into_user_properties() -> None:
    """The fixture appends ``("cost_usd", total)`` on teardown."""
    user_properties: list[tuple[str, Any]] = []
    fake_node = SimpleNamespace(user_properties=user_properties)
    fake_request = SimpleNamespace(node=fake_node)

    from evals.conftest import record_cost

    fn = getattr(record_cost, "__wrapped__", record_cost)
    gen = fn(fake_request)  # type: ignore[arg-type]
    appender = next(gen)
    appender(0.1)
    appender(0.2)
    appender(0.05)
    # Drive teardown.
    with pytest.raises(StopIteration):
        next(gen)

    assert user_properties == [("cost_usd", pytest.approx(0.35))]


def test_record_cost_fixture_zero_when_unused() -> None:
    """No appends → recorded total is exactly 0.0 (still records the entry)."""
    user_properties: list[tuple[str, Any]] = []
    fake_node = SimpleNamespace(user_properties=user_properties)
    fake_request = SimpleNamespace(node=fake_node)

    from evals.conftest import record_cost

    fn = getattr(record_cost, "__wrapped__", record_cost)
    gen = fn(fake_request)  # type: ignore[arg-type]
    next(gen)  # acquire appender, do nothing
    with pytest.raises(StopIteration):
        next(gen)

    assert user_properties == [("cost_usd", 0)]


# ---------------------------------------------------------------------------
# Wrapper does not perform LLM calls during these tests — sanity guard
# ---------------------------------------------------------------------------


def test_judge_wrapper_does_not_call_litellm_on_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing the wrapper must not import-time-call any litellm method."""
    # Replace the litellm module with a sentinel; if anything in the wrapper
    # accidentally hits it during ``__init__`` / identity methods we'll see
    # an AttributeError below.
    sentinel = types.ModuleType("litellm_sentinel")
    monkeypatch.setitem(sys.modules, "litellm", sentinel)

    wrapper = DeepEvalLitellmWrapper(model="openai/gpt-4o-mini")
    # Identity methods must not touch litellm.
    assert wrapper.get_model_name() == "openai/gpt-4o-mini"
    assert wrapper.load_model() is wrapper
