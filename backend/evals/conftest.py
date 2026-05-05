"""Shared fixtures for agent evals: judge LLM, cost tracking, run helpers.

Loaded automatically by pytest for any test under ``backend/evals/``. Fixtures
here are intentionally agent-agnostic — per-node test files (``test_planner``,
``test_critic``, ...) compose them into concrete invocations.

Notes
-----
* ``deepeval`` is an optional extra (``--extra evals``); the imports below stay
  lazy / guarded so module collection does not fail without it. Tests that
  actually need DeepEval metrics should ``pytest.importorskip("deepeval")``.
* The cost-cap plugin is registered via ``pytest_plugins`` so the
  ``--cost-cap`` / ``--smoke`` options are available to every eval test.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# uv treats this project as a virtual workspace, so `evals/` is never copied
# into site-packages. Pytest doesn't always materialise `pythonpath=` /
# top-level conftest sys.path mutations before this conftest is imported
# (observed on `uv run` under CI). Mutate sys.path inline so the absolute
# import below resolves regardless of how pytest was invoked.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from evals.lib.judge import DeepEvalLitellmWrapper  # noqa: E402

# Re-export agent node entry points so per-node test files can import them
# from a single canonical location (``from evals.conftest import planner``).
# Tasks 057–059 use these to assemble ``run_node`` / ``run_full_pipeline``
# invocations. Imports are guarded so ``--extra agents`` stays optional for
# bare scaffolding tests; missing modules surface as ``None`` and tests that
# need them should ``pytest.importorskip`` accordingly.
try:
    from app.agents.builtin.general.nodes import (  # noqa: F401
        critic,
        diagram,
        planner,
        researcher,
    )
except ImportError:  # pragma: no cover - exercised when --extra agents absent
    planner = diagram = critic = researcher = None  # type: ignore[assignment]

try:
    from app.agents.builtin.diagram_explainer.graph import run as run_explainer  # noqa: F401
except ImportError:  # pragma: no cover
    run_explainer = None  # type: ignore[assignment]

# Register the cost-cap plugin so its CLI options + hooks are active for the
# whole evals/ tree. Pytest only honours ``pytest_plugins`` in the *root*
# conftest of a collection tree — declaring it here is exactly that.
pytest_plugins = ["evals.lib.pytest_cost_cap"]


# ---------------------------------------------------------------------------
# Judge model fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def eval_model() -> DeepEvalLitellmWrapper:
    """LLM judge model (separate from agent model). Configured via env.

    Environment
    -----------
    EVAL_MODEL:
        LiteLLM identifier. Defaults to ``openai/gpt-4o-mini``.
    EVAL_LLM_KEY:
        Provider API key (LiteLLM also reads provider-specific env vars).
    EVAL_LLM_BASE_URL:
        Optional base URL override (self-hosted gateways).
    """
    return DeepEvalLitellmWrapper(
        model=os.environ.get("EVAL_MODEL", "openai/gpt-4o-mini"),
        api_key=os.environ.get("EVAL_LLM_KEY"),
        base_url=os.environ.get("EVAL_LLM_BASE_URL"),
    )


# ---------------------------------------------------------------------------
# Cost recording
# ---------------------------------------------------------------------------


@pytest.fixture
def record_cost(request: pytest.FixtureRequest):
    """Per-test cost recorder.

    Tests append decimals (``record_cost(0.0123)``) for each LLM call they
    make. On teardown the total is stored on the report's ``user_properties``
    so the cost-cap plugin can sum it across the run.
    """
    costs: list[float] = []

    def _append(value: float) -> None:
        costs.append(float(value))

    yield _append

    request.node.user_properties.append(("cost_usd", sum(costs)))


# ---------------------------------------------------------------------------
# Golden dataset loader
# ---------------------------------------------------------------------------


_GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def load_golden(filename: str, *, category: str | None = None) -> list[dict]:
    """Load a JSON golden dataset from ``evals/golden/``.

    Parameters
    ----------
    filename:
        Basename or relative path inside ``golden/`` (``"planner.json"`` or
        ``"sub/foo.json"``).
    category:
        Optional filter — keeps only entries whose ``category`` field equals
        the supplied value. Entries without a ``category`` key are dropped
        when a filter is supplied.

    Returns an empty list if the file holds an empty array (placeholder
    datasets shipped before tasks 057–059 land their real cases).
    """
    path = _GOLDEN_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"golden dataset not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data: Any = json.load(fh)

    if not isinstance(data, list):
        raise ValueError(
            f"golden dataset {filename!r} must be a JSON array, got {type(data).__name__}"
        )

    if category is None:
        return data
    return [
        entry
        for entry in data
        if isinstance(entry, dict) and entry.get("category") == category
    ]


# ---------------------------------------------------------------------------
# Run helpers (filled in by tasks 057–059)
# ---------------------------------------------------------------------------


@pytest.fixture
async def run_node():
    """Helper to invoke a single node with stub deps. Returns ``NodeOutput``.

    Used by ``test_planner.py`` / ``test_critic.py`` / ``test_researcher.py`` /
    ``test_explainer.py``. Tasks 057–059 will wire the concrete invocation —
    constructing :class:`AgentState`, stub :class:`LimitsEnforcer`,
    :class:`ContextManager`, and a fake ``ToolExecutor`` — and return the
    final :class:`NodeOutput` from the node's async iterator.

    Until those tasks land this fixture raises :class:`NotImplementedError`
    when invoked, which keeps the dependency wiring obvious.
    """

    async def _run_node(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "run_node helper is wired by tasks 057-059; supply your own runner "
            "until then."
        )

    return _run_node


@pytest.fixture
async def run_full_pipeline():
    """Helper to invoke the general agent end-to-end. Returns ``InvokeResult``.

    Used by ``test_e2e.py``. Tasks 057–059 will wire this against a scrubbed
    test database (or pure-stub tool executor) so e2e cases can run against
    the real LangGraph without touching production data.
    """

    async def _run_full_pipeline(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "run_full_pipeline helper is wired by tasks 057-059; supply your "
            "own runner until then."
        )

    return _run_full_pipeline
