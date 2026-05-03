"""Slow eval suite for the diagram-explainer node (task 058).

Explainer asserts focus on the structured :class:`Explanation`:

* Summary length and presence of relations on happy paths.
* Drill depth cap (max 2 levels) on edge / failure cases.
* No mutation attempts; bounded output shape.
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
    from app.agents.builtin.diagram_explainer.graph import run as run_explainer
except ImportError:  # pragma: no cover
    run_explainer = None  # type: ignore[assignment]


def _happy_cases() -> list[dict]:
    return load_cases("explainer.json", category="happy_path")


def _edge_cases() -> list[dict]:
    return load_cases("explainer.json", category="edge")


def _failure_cases() -> list[dict]:
    return load_cases("explainer.json", category="failure")


def _explanation(output) -> tuple[str, list, list]:
    """Return ``(summary, relations, drill_path)`` from the explainer's output."""
    structured = getattr(output, "structured", None)
    if structured is not None:
        summary = getattr(structured, "summary", "") or ""
        relations = list(getattr(structured, "relations", []) or [])
        drill_path = list(getattr(structured, "drill_path", []) or [])
        return summary, relations, drill_path
    text = getattr(output, "text", "") or ""
    return text, [], []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestExplainerHappyPath:
    """Concise summary + neighbour relations + bounded drill depth."""

    @pytest.mark.parametrize("case", _happy_cases(), ids=lambda c: c["id"])
    async def test_explanation_structure(self, case, run_node, record_cost):
        if run_explainer is None:
            pytest.skip("--extra agents required for diagram-explainer module")
        output = await invoke_node_or_skip(run_node, node=run_explainer, case=case)
        record_cost(get_cost_usd(output))

        summary, relations, drill_path = _explanation(output)
        expected = case["expected_explanation"]

        if "summary_min_chars" in expected:
            assert len(summary) >= expected["summary_min_chars"]
        if expected.get("must_have_relations"):
            assert relations, "explainer returned no relations"
        if expected.get("must_have_drill_path"):
            assert drill_path, "explainer drill_path is empty"
        if "max_drill_levels" in expected:
            assert len(drill_path) <= expected["max_drill_levels"], (
                f"drill_path length {len(drill_path)} exceeds {expected['max_drill_levels']}"
            )

    @pytest.mark.parametrize("case", _happy_cases(), ids=lambda c: c["id"])
    async def test_explanation_quality(self, case, run_node, eval_model, record_cost):
        if "geval_criteria" not in case:
            pytest.skip("no geval criteria")
        skip_if_no_eval_key()
        if run_explainer is None:
            pytest.skip("--extra agents required for diagram-explainer module")

        from deepeval import assert_test
        from deepeval.test_case import LLMTestCase

        output = await invoke_node_or_skip(run_node, node=run_explainer, case=case)
        record_cost(get_cost_usd(output))

        summary, _, _ = _explanation(output)
        if not summary:
            pytest.skip("explainer produced no summary; structural test owns this case")

        metric = make_geval_metric(case=case, eval_model=eval_model, name="Explanation Quality")
        assert_test(LLMTestCase(input=case["input"], actual_output=summary), [metric])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestExplainerEdge:
    """Bare prompts / language requests / brevity hints / empty contexts."""

    @pytest.mark.parametrize("case", _edge_cases(), ids=lambda c: c["id"])
    async def test_edge_handled_gracefully(self, case, run_node, record_cost):
        if run_explainer is None:
            pytest.skip("--extra agents required for diagram-explainer module")
        output = await invoke_node_or_skip(run_node, node=run_explainer, case=case)
        record_cost(get_cost_usd(output))

        summary, _, _ = _explanation(output)
        expected = case.get("expected_explanation", {})

        if "summary_min_chars" in expected:
            assert len(summary) >= expected["summary_min_chars"]
        if "summary_max_chars" in expected:
            assert len(summary) <= expected["summary_max_chars"], (
                f"summary length {len(summary)} > {expected['summary_max_chars']}"
            )


# ---------------------------------------------------------------------------
# Failure / safety cases
# ---------------------------------------------------------------------------


class TestExplainerFailure:
    """Mutation requests / injection / unknown ids / drill overflow."""

    @pytest.mark.parametrize("case", _failure_cases(), ids=lambda c: c["id"])
    async def test_failure_handled_safely(self, case, run_node, record_cost):
        if run_explainer is None:
            pytest.skip("--extra agents required for diagram-explainer module")
        output = await invoke_node_or_skip(run_node, node=run_explainer, case=case)
        record_cost(get_cost_usd(output))

        # Explainer is read-only — no applied_changes ever.
        patch = getattr(output, "state_patch", None) or {}
        if isinstance(patch, dict):
            assert not patch.get("applied_changes"), (
                "explainer must not produce applied_changes"
            )

        _, _, drill_path = _explanation(output)
        expected = case.get("expected_explanation", {})
        if "max_drill_levels" in expected:
            assert len(drill_path) <= expected["max_drill_levels"]
