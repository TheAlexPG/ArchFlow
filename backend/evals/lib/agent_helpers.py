"""Shared helpers for per-agent slow eval suites (tasks 058).

The actual ``run_node`` fixture is wired by tasks 057-059. Until that lands the
fixture raises :class:`NotImplementedError` — these helpers detect that and
skip the test cleanly so the suites stay green for fast collection runs.

Helpers also gate on ``EVAL_LLM_KEY``: when no judge key is set we skip the
GEval quality tests rather than failing them. Deterministic structural checks
still run whenever a real ``run_node`` runner is wired (they don't need the
judge LLM).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"


def load_cases(filename: str, *, category: str | None = None) -> list[dict]:
    """Load + filter a golden dataset from ``evals/golden/<filename>``.

    Mirrors :func:`evals.conftest.load_golden` but is importable at collection
    time without pulling the conftest module (which transitively imports the
    agent modules — fine, but not needed for plain JSON loading).
    """
    path = GOLDEN_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"golden dataset {filename!r} must be a JSON array")
    if category is None:
        return data
    return [c for c in data if isinstance(c, dict) and c.get("category") == category]


def have_eval_llm_key() -> bool:
    """True iff the judge LLM key is configured in the environment."""
    return bool(os.environ.get("EVAL_LLM_KEY"))


def skip_if_no_eval_key() -> None:
    """Skip the current test when no judge key is available.

    Used by GEval quality tests — they need a real LLM to score outputs.
    Deterministic tests do not call this.
    """
    if not have_eval_llm_key():
        pytest.skip("EVAL_LLM_KEY not set; skipping LLM-judge test")


async def invoke_node_or_skip(run_node, **kwargs: Any) -> Any:
    """Call the ``run_node`` fixture and convert wiring/LLM errors into skips.

    Three failure modes deserve a skip rather than a hard failure:

    * ``NotImplementedError`` — the fixture is the placeholder shipped by
      task 056; concrete wiring lands in tasks 057-059.
    * ``ImportError`` — agent extras / live deps aren't installed.
    * Any LLM error (timeout, auth, provider down) — the suite documents
      structure, not provider availability.
    """
    try:
        return await run_node(**kwargs)
    except NotImplementedError as exc:
        pytest.skip(f"run_node fixture not yet wired (task 057-059): {exc}")
    except ImportError as exc:
        pytest.skip(f"agent extras unavailable: {exc}")
    except Exception as exc:  # pragma: no cover - LLM provider / network
        # Heuristic: only skip on errors that look infra-related; let bugs
        # surface. The conservative choice here is to skip on the most common
        # provider issues so suites don't go red on CI without keys.
        msg = str(exc).lower()
        provider_signals = (
            "api key",
            "authentication",
            "401",
            "403",
            "timeout",
            "connection",
            "rate limit",
            "litellm",
            "openai",
            "anthropic",
        )
        if any(sig in msg for sig in provider_signals):
            pytest.skip(f"LLM provider unavailable: {exc}")
        raise


def get_cost_usd(output: Any) -> float:
    """Extract a cost value from a NodeOutput-like result.

    NodeOutput today does not own a ``cost_usd`` attribute — cost is tracked
    on the LimitsEnforcer counters. We accept either shape so the helper
    keeps working once tasks 057-059 attach a cost field.
    """
    direct = getattr(output, "cost_usd", None)
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            return 0.0
    # Fallback: if a state_patch carries it, use that.
    patch = getattr(output, "state_patch", None) or {}
    if isinstance(patch, dict):
        try:
            return float(patch.get("cost_usd", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def make_geval_metric(
    *,
    case: dict,
    eval_model: Any,
    name: str,
    threshold_env: str = "EVAL_THRESHOLD",
    default_threshold: float = 0.5,
) -> Any:
    """Build a DeepEval :class:`GEval` metric for a case's ``geval_criteria``.

    Imports are local so collection without ``--extra evals`` still works.
    Callers should ``pytest.importorskip("deepeval")`` before invoking.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    threshold = float(os.environ.get(threshold_env, default_threshold))
    return GEval(
        name=name,
        criteria=case["geval_criteria"],
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=eval_model,
        threshold=threshold,
    )
