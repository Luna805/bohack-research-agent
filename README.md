# BudgetLab

BudgetLab is a budget-aware, evidence-bound research loop for tabular classification. One
LLM call per round proposes two falsifiable hypotheses as strict `ExperimentSpec`s; plain
Python owns everything that decides an outcome: data boundaries, real training, metrics,
verdicts, budgets, stop rules, confirmation, delivery freezing and the one-shot holdout score.

## Install

```bash
uv sync --frozen --extra dev --extra llm        # or: python -m uv sync ...
```

Without uv: `pip install -r requirements.lock pytest ruff "pydantic-ai-slim[openai]==2.68.0"`.

## Run

```bash
python -m budgetlab.cli prepare --task bank_marketing          # download UCI data, seal 20% holdout
python -m budgetlab.cli research --config configs/bank_marketing.yaml --system random_search
python -m budgetlab.cli research --config configs/bank_marketing.yaml --system budgetlab --proposer scripted
python -m budgetlab.cli evaluate --run-id <RUN_ID>             # once per run, after freezing
python -m budgetlab.cli reproduce --run-id <RUN_ID>
python -m budgetlab.cli replay --run-id <RUN_ID>
```

Live LLM (OpenAI-compatible hosted model):

1. copy `.env.example` to `.env` and fill `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`;
2. set positive `max_llm_requests` / `max_llm_tokens` in the config (this is the spending authorisation);
3. `python -m budgetlab.cli probe-llm --config configs/bank_marketing.yaml` - one real request
   with the final `ProposalBatch` schema; if tool output fails, try `llm.output_mode: native`
   or `prompted`;
4. `python -m budgetlab.cli research --config configs/bank_marketing.yaml --system budgetlab --proposer llm`.

## Systems

| system | what runs between baseline and confirmation |
|---|---|
| `random_search` | zero-token sampler over the same legal space (models, class weights, feature actions) |
| `budgetlab_no_schedule` | proposer loop with screening, dedup, budget and stop rules |
| `budgetlab` | adds rule-scheduled tool search (start and on stagnation), replan mode and on-demand critic |

## What one run does

1. `prepare` writes `data/prepared/<task>/development.csv` and `data/sealed/<task>/holdout.csv`.
   Research code only loads the development file.
2. The scenario card (`budgetlab/tasks/cards/*.yaml`) fixes prediction time and field
   availability; e.g. Bank Marketing's `duration` is post-outcome and is excluded.
3. Baseline (logistic regression) + calibration on 5 extra split seeds -> `min_effect` =
   max(floor, noise) is frozen into `contract.json` before any proposal.
4. Loop: build compact context -> proposer (2 candidates) -> program screening (schema, legal
   columns, comparator, duplicate hash) -> run both when cheap -> paired same-fold verdicts vs
   baseline, vs previous best and vs the hypothesis' own comparator -> stop rules.
5. Best candidate passing vs baseline is re-checked on 3 unseen split seeds; only
   `confirmed_pass` is delivered, otherwise the baseline is. Full-development refit, frozen.
6. `evaluate` scores the frozen model once on the sealed holdout.

Every LLM request is reserved before and settled after (`budget.json`, `llm_calls.jsonl`);
failed requests without usage are booked as unknown, never as free.

## Run directory

`protocol.json`, `contract.json`, `scenario_card.json`, `eda.json`, `calibration.json`,
`split_manifest.json`, `events.jsonl`, `budget.json`, `llm_calls.jsonl`, `llm/*` (exact
contexts and outputs), `rounds/round-NN.json` (proposal, rejected / selected / not_run with
reasons, trigger source), `experiments/<id>.json` (spec, result, all verdicts, logs),
`confirmation.json`, `delivery/`, `summary.json`, `report.md`, `final_evaluation.json`.

## Tests

```bash
python -m pytest -q          # includes a PydanticAI FunctionModel loop: metering, dedup, zero-budget stop
ruff check .
```

## Status (2026-11-14)

Done: deterministic engine, Bank Marketing task + sealed holdout, multi-round loop with two
candidates, dedup, stop rules, tool-search scheduling, direction attribution, metered
PydanticAI proposer/critic (tested with a local FunctionModel), one-shot holdout evaluation.

Not yet: a real hosted-model run, MLE-bench/Kaggle tasks, benchmark matrix runner, UI,
lesson bank. Training runs in child processes with timeouts; this is not an OS sandbox.
