# Agent Evals

## Quick start

```bash
cd backend && make -C evals fast              # CI-safe, no LLM cost
cd backend && make -C evals slow              # Requires EVAL_LLM_KEY env
```

## Suites

- `fast` — deterministic, runs in main CI on every PR. Covers: draft policy, permission checks, tool correctness, compaction, budget enforcement, layout validation.
- `slow` — LLM-judge GEval tests. Covers: planner, diagram agent, critic, researcher, explainer, e2e. Triggered manually via `eval.yml` workflow dispatch.
- `e2e` — full general-agent runs, release-gate only ($5/run cap). Included in `make -C evals eval-release`.

## Targets

| Target | Command | Notes |
|---|---|---|
| `fast` | `make -C evals fast` | All deterministic tests |
| `slow` | `make -C evals slow` | All LLM-judge tests |
| `eval-release` | `make -C evals eval-release` | `fast` + `slow` + release report |
| `eval-baseline` | `make -C evals eval-baseline` | Save new baseline snapshots |
| `eval-quick` | `make -C evals eval-quick` | Smoke run across all evals |

## Environment variables

| Variable | Purpose |
|---|---|
| `EVAL_MODEL` | Judge model (e.g. `openai/gpt-4o-mini`) |
| `EVAL_LLM_KEY` | Judge LLM API key |
| `EVAL_LLM_BASE_URL` | Optional custom base URL for the judge model |
| `EVAL_THRESHOLD_PROFILE` | `lenient` (default, CI) or `strict` (release gate) |

## CI

- **Every PR** — `test.yml` runs `make -C evals fast` (deterministic, zero LLM cost).
- **Manual** — `eval.yml` workflow dispatch runs any suite (fast/slow/all/single-test) against the `eval-llm-keys` GitHub environment. Artifacts are uploaded to the Actions run.

### Running a single test manually

In the `eval.yml` dispatch UI, select suite `single-test` and set `test_path` to the pytest node ID relative to `backend/`, e.g.:

```
evals/test_planner.py::TestPlannerAgent::test_basic_plan
```

## Setting up the `eval-llm-keys` GitHub environment

1. Go to **Settings → Environments → New environment** and name it `eval-llm-keys`.
2. Optionally add required reviewers and branch protection to gate who can trigger costed runs.
3. Add the following secrets to the environment:

   | Secret | Value |
   |---|---|
   | `EVAL_MODEL` | e.g. `openai/gpt-4o-mini` |
   | `EVAL_LLM_KEY` | API key for the judge model provider |
   | `EVAL_LLM_BASE_URL` | (optional) custom base URL |

4. Trigger via **Actions → Agent Evals (slow, costed) → Run workflow**.
