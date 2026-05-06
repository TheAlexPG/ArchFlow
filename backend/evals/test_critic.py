"""Slow eval suite for the critic node (task 058).

Critic asserts focus on the verdict (APPROVE | REVISE) and the presence of
``revision_request`` when REVISE. Failure cases include destructive bulk
operations and prompt-injection attempts to coerce APPROVE.
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
    from app.agents.builtin.general.nodes.critic import run as run_critic
except ImportError:  # pragma: no cover
    run_critic = None  # type: ignore[assignment]


def _happy_cases() -> list[dict]:
    return load_cases("critic.json", category="happy_path")


def _edge_cases() -> list[dict]:
    return load_cases("critic.json", category="edge")


def _failure_cases() -> list[dict]:
    return load_cases("critic.json", category="failure")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestCriticHappyPath:
    """Critic should APPROVE when applied_changes cover the goal."""

    @pytest.mark.parametrize("case", _happy_cases(), ids=lambda c: c["id"])
    async def test_verdict_structure(self, case, run_node, record_cost):
        if run_critic is None:
            pytest.skip("--extra agents required for critic module")
        output = await invoke_node_or_skip(run_node, node=run_critic, case=case)
        record_cost(get_cost_usd(output))

        critique = getattr(output, "structured", None)
        assert critique is not None, "critic returned no structured output"
        assert hasattr(critique, "verdict")
        assert critique.verdict in ("APPROVE", "REVISE")
        assert critique.verdict == case["expected_verdict"], (
            f"expected {case['expected_verdict']!r}, got {critique.verdict!r}"
        )

    @pytest.mark.parametrize("case", _happy_cases(), ids=lambda c: c["id"])
    async def test_verdict_quality(self, case, run_node, eval_model, record_cost):
        if "geval_criteria" not in case:
            pytest.skip("no geval criteria")
        skip_if_no_eval_key()
        if run_critic is None:
            pytest.skip("--extra agents required for critic module")

        from deepeval import assert_test
        from deepeval.test_case import LLMTestCase

        output = await invoke_node_or_skip(run_node, node=run_critic, case=case)
        record_cost(get_cost_usd(output))

        critique = getattr(output, "structured", None)
        if critique is None:
            pytest.skip("critic produced no structured verdict; structural test owns this case")

        actual = (
            critique.model_dump_json() if hasattr(critique, "model_dump_json") else str(critique)
        )
        metric = make_geval_metric(case=case, eval_model=eval_model, name="Critique Quality")
        assert_test(LLMTestCase(input=case["input"], actual_output=actual), [metric])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCriticEdge:
    """Partial coverage / no changes / extraneous changes -> REVISE."""

    @pytest.mark.parametrize("case", _edge_cases(), ids=lambda c: c["id"])
    async def test_edge_revises_with_request(self, case, run_node, record_cost):
        if run_critic is None:
            pytest.skip("--extra agents required for critic module")
        output = await invoke_node_or_skip(run_node, node=run_critic, case=case)
        record_cost(get_cost_usd(output))

        critique = getattr(output, "structured", None)
        assert critique is not None
        assert critique.verdict == case["expected_verdict"]
        if critique.verdict == "REVISE":
            assert critique.revision_request, (
                "REVISE verdict requires a non-empty revision_request"
            )


# ---------------------------------------------------------------------------
# Failure / safety cases
# ---------------------------------------------------------------------------


class TestCriticFailure:
    """Destructive / injected / wrong-tech goals -> REVISE, never APPROVE."""

    @pytest.mark.parametrize("case", _failure_cases(), ids=lambda c: c["id"])
    async def test_failure_does_not_approve(self, case, run_node, record_cost):
        if run_critic is None:
            pytest.skip("--extra agents required for critic module")
        output = await invoke_node_or_skip(run_node, node=run_critic, case=case)
        record_cost(get_cost_usd(output))

        critique = getattr(output, "structured", None)
        assert critique is not None, "critic returned nothing on a failure case"
        assert critique.verdict == "REVISE", (
            f"failure case must REVISE, got {critique.verdict!r}"
        )
        assert critique.revision_request, "REVISE must include a revision_request"
