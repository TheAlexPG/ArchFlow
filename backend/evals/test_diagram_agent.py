"""Slow eval suite for the diagram-agent node (task 058).

Diagram-agent is the only mutating node — assertions focus on:

* Applied-changes count + tool coverage on happy paths.
* Read-only mode / unsupported actions / cycles / max_steps on failures.
* GEval scores plan execution quality when ``EVAL_LLM_KEY`` is set.

Tests skip when the ``run_node`` fixture is the task-056 placeholder.
"""

from __future__ import annotations

import pytest

pytest.importorskip("deepeval")

from evals.lib.agent_helpers import (  # noqa: E402
    get_cost_usd,
    invoke_node_or_skip,
    load_cases,
    make_geval_metric,
    skip_if_no_eval_key,
)

try:
    from app.agents.builtin.general.nodes.diagram import run as run_diagram
except ImportError:  # pragma: no cover
    run_diagram = None  # type: ignore[assignment]


def _happy_cases() -> list[dict]:
    return load_cases("diagram.json", category="happy_path")


def _edge_cases() -> list[dict]:
    return load_cases("diagram.json", category="edge")


def _failure_cases() -> list[dict]:
    return load_cases("diagram.json", category="failure")


def _applied_changes(output) -> list[dict]:
    """Pull applied_changes from a NodeOutput's state_patch."""
    patch = getattr(output, "state_patch", None) or {}
    if not isinstance(patch, dict):
        return []
    return list(patch.get("applied_changes") or [])


def _tools_called(output) -> set[str]:
    """Best-effort: extract tool names from the output's state_patch messages."""
    patch = getattr(output, "state_patch", None) or {}
    if not isinstance(patch, dict):
        return set()
    msgs = patch.get("messages") or []
    names: set[str] = set()
    for m in msgs:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name")
            if name:
                names.add(name)
        if m.get("role") == "tool" and m.get("name"):
            names.add(m["name"])
    return names


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestDiagramAgentHappyPath:
    """Plan execution: applied_changes count + required tool coverage."""

    @pytest.mark.parametrize("case", _happy_cases(), ids=lambda c: c["id"])
    async def test_applied_changes_structure(self, case, run_node, record_cost):
        if run_diagram is None:
            pytest.skip("--extra agents required for diagram module")
        output = await invoke_node_or_skip(run_node, node=run_diagram, case=case)
        record_cost(get_cost_usd(output))

        expected = case["expected_outcome"]
        applied = _applied_changes(output)

        if "min_applied_changes" in expected:
            assert len(applied) >= expected["min_applied_changes"], (
                f"expected >= {expected['min_applied_changes']} changes, got {len(applied)}"
            )
        if "max_applied_changes" in expected:
            assert len(applied) <= expected["max_applied_changes"]

        if expected.get("no_forced_finalize"):
            assert getattr(output, "forced_finalize", None) in (None, ""), (
                f"unexpected forced_finalize={output.forced_finalize!r}"
            )

        tools = _tools_called(output)
        for required in expected.get("must_call_tools", []):
            # Tool may not have been logged into messages; only enforce when
            # we observed any tool calls at all.
            if tools:
                assert required in tools, (
                    f"diagram-agent did not call {required!r}; called {tools!r}"
                )

    @pytest.mark.parametrize("case", _happy_cases(), ids=lambda c: c["id"])
    async def test_execution_quality(self, case, run_node, eval_model, record_cost):
        if "geval_criteria" not in case:
            pytest.skip("no geval criteria")
        skip_if_no_eval_key()
        if run_diagram is None:
            pytest.skip("--extra agents required for diagram module")

        from deepeval import assert_test
        from deepeval.test_case import LLMTestCase

        output = await invoke_node_or_skip(run_node, node=run_diagram, case=case)
        record_cost(get_cost_usd(output))

        applied = _applied_changes(output)
        actual = (
            getattr(output, "text", None)
            or "\n".join(f"{c.get('action')} {c.get('name', c.get('target_id'))}" for c in applied)
            or "(no output)"
        )
        metric = make_geval_metric(
            case=case, eval_model=eval_model, name="Diagram Execution Quality"
        )
        assert_test(LLMTestCase(input=case["input"], actual_output=actual), [metric])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestDiagramAgentEdge:
    """Idempotency / empty plan / read-only steps / partial failure recovery."""

    @pytest.mark.parametrize("case", _edge_cases(), ids=lambda c: c["id"])
    async def test_edge_handled_gracefully(self, case, run_node, record_cost):
        if run_diagram is None:
            pytest.skip("--extra agents required for diagram module")
        output = await invoke_node_or_skip(run_node, node=run_diagram, case=case)
        record_cost(get_cost_usd(output))

        expected = case.get("expected_outcome", {})
        applied = _applied_changes(output)

        if "max_applied_changes" in expected:
            cap = expected["max_applied_changes"]
            assert len(applied) <= cap, (
                f"edge case produced {len(applied)} changes; expected <= {cap}"
            )
        if expected.get("no_forced_finalize"):
            assert getattr(output, "forced_finalize", None) in (None, "")


# ---------------------------------------------------------------------------
# Failure / safety cases
# ---------------------------------------------------------------------------


class TestDiagramAgentFailure:
    """Read-only mode / invalid kinds / cycles / max-steps."""

    @pytest.mark.parametrize("case", _failure_cases(), ids=lambda c: c["id"])
    async def test_failure_handled_safely(self, case, run_node, record_cost):
        if run_diagram is None:
            pytest.skip("--extra agents required for diagram module")
        output = await invoke_node_or_skip(run_node, node=run_diagram, case=case)
        record_cost(get_cost_usd(output))

        expected = case.get("expected_outcome", {})
        applied = _applied_changes(output)

        if "max_applied_changes" in expected:
            assert len(applied) <= expected["max_applied_changes"], (
                f"failure case unexpectedly applied {len(applied)} changes"
            )

        if "expect_forced_finalize_in" in expected:
            forced = getattr(output, "forced_finalize", None)
            allowed = expected["expect_forced_finalize_in"]
            assert forced in allowed, (
                f"expected forced_finalize in {allowed!r}, got {forced!r}"
            )

        if expected.get("expect_denied"):
            # In read_only mode no mutations should land. We've already
            # checked max_applied_changes; the stricter assertion is = 0.
            assert len(applied) == 0
