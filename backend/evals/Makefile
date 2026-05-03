.PHONY: fast slow planner diagram critic researcher explainer e2e draft permission tool budget compact layout eval-quick eval-release eval-baseline

PYTEST = uv run --extra agents --extra dev --extra evals pytest

fast: draft permission tool compact budget layout
slow: planner diagram critic researcher explainer e2e

draft:
	$(PYTEST) evals/test_draft_policy.py -v
permission:
	$(PYTEST) evals/test_permission.py -v
tool:
	$(PYTEST) evals/test_tool_correctness.py -v
compact:
	$(PYTEST) evals/test_compaction.py -v
budget:
	$(PYTEST) evals/test_budget.py -v
layout:
	$(PYTEST) evals/test_layout.py -v

planner:
	$(PYTEST) evals/test_planner.py -v --cost-cap=0.50
diagram:
	$(PYTEST) evals/test_diagram_agent.py -v --cost-cap=2.00
critic:
	$(PYTEST) evals/test_critic.py -v --cost-cap=0.50
researcher:
	$(PYTEST) evals/test_researcher.py -v --cost-cap=0.50
explainer:
	$(PYTEST) evals/test_explainer.py -v --cost-cap=0.20
e2e:
	$(PYTEST) evals/test_e2e.py -v --cost-cap=5.00

eval-quick:
	$(PYTEST) evals/ --smoke -v

eval-release: fast slow
	@python evals/lib/release_report.py reports/

eval-baseline:
	@python evals/lib/baseline.py save
