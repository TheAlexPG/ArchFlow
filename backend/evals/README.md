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
| `eval-golden` | `make -C evals eval-golden` | Live supervisor+sub-agents run against local Qwen (mocked DB) |

## Environment variables

| Variable | Purpose |
|---|---|
| `EVAL_MODEL` | Judge model (e.g. `openai/gpt-4o-mini`) |
| `EVAL_LLM_KEY` | Judge LLM API key |
| `EVAL_LLM_BASE_URL` | Optional custom base URL for the judge model |
| `EVAL_THRESHOLD_PROFILE` | `lenient` (default, CI) or `strict` (release gate) |

## Golden suite (live local Qwen)

The `eval-golden` target exercises the full general-agent graph
(supervisor → planner / researcher / diagram → finalize) against a **real**
local Qwen / LM Studio endpoint while **mocking** every database and
service-layer call. The LLM is the only live dependency — the whole point is
to catch when our prompts or graph cause Qwen to misbehave.

Skipped by default. Enable explicitly:

```bash
cd backend
RUN_GOLDEN_EVALS=1 make -C evals eval-golden
```

Files:

- `evals/test_golden_investigate.py` — read-only "explain the diagram" cases.
- `evals/test_golden_create_basic.py` — basic creation cases (new store + place
  + connect).
- `evals/golden_runtime.py` — shared scaffolding: seeded in-memory workspace,
  `FakeSession`, monkeypatch helpers for object/diagram/connection services +
  access service + layout engine.

Configuration via environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `RUN_GOLDEN_EVALS` | _(unset)_ | Must be `1` (or `true`) to enable. |
| `GOLDEN_EVAL_BASE_URL` | `http://192.168.0.146:11434/v1` | LM Studio / Ollama endpoint. |
| `GOLDEN_EVAL_MODEL` | `qwen/qwen3.6-35b-a3b` | Model id served at the endpoint. |

Each case finishes in ~30-90s on a healthy LM Studio instance. Assertions are
intentionally lenient on wording (Qwen rephrases on every run) and strict on
structure (a researcher delegation happened, the right tools were called,
applied_changes counts match). Cases that consistently flake on Qwen quirks
(e.g. picking 'unidirectional' when the prompt says 'bidirectional') are
marked `xfail` with a clear reason — that flake itself is signal we want to
keep visible.

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
