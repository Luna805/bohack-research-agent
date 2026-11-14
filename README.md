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

## Chat research page (offline demonstration)

Install the optional UI dependencies with `uv sync --frozen --extra dev --extra llm --extra ui`,
then run `uv run streamlit run budgetlab/ui/app.py`. Choose Bank Marketing, Adult Income,
or the offline Breast Cancer smoke task, confirm its protocol card, prepare the data,
and start research. Bank and Adult preparation download public data on first use.
You can also attach a binary-classification CSV in the chat, select its target and positive
class, and confirm each field's availability before preparing a local task. The page labels
scripted proposals as **not using an LLM**. Every score
is read from the run artifacts. Holdout scoring requires a separate button and can run once.
For a quick demonstration, select an example and click **用所选示例开始**. After a run finishes,
click **开始另一个任务** to clear the page state without deleting the saved evidence.
The sidebar can reopen a local run after a browser refresh, including one without a final
summary. While a new run is active, step cards update automatically every two seconds. The system comparison
view reads the newest `results/final-*` matrix, or labels `results/dev-*` as development data
when no formal matrix is available.
For a repeatable upload demo, attach `examples/student_risk/student_risk.csv` and use the
explicit **载入演示协议（人工标准答案）** button. Review the excluded `G1`, `G2`, `G3` and
`absences` fields before confirming; this card was written by a person, not inferred by an LLM.

Free-form protocol drafting and open-ended QA depend on A's agent interfaces in
`docs/INTERFACES.md`. The no-LLM path uses human-confirmed cards and zero-token quick answers.

## Tests

```bash
python -m pytest -q          # includes a PydanticAI FunctionModel loop: metering, dedup, zero-budget stop
ruff check .
```

## Status (2026-11-14)

Done: deterministic engine, Bank Marketing task + sealed holdout, multi-round loop with two
candidates, dedup, stop rules, tool-search scheduling, direction attribution, metered
PydanticAI proposer/critic (tested with a local FunctionModel), one-shot holdout evaluation.

Also available: the benchmark matrix runner, Adult task, chat research page, and development
comparison data. Not yet verified: a real hosted-model run, free-form protocol agent,
open-ended QA agent, formal matrix results, or lesson bank. Training runs in child
processes with timeouts; this is not an OS sandbox.
