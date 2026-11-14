# BudgetLab run `20261114T030621Z-budgetlab-a40242`

- task: `bank_marketing` · system: `budgetlab` · proposals: `scripted`
- primary metric: `f1_macro` (development 5-fold CV); frozen min_effect = 0.0020
- stop reason: `no_valid_candidates` · wall time: 82.33 s
- code version: `165a031`

## Result

| item | value |
|---|---|
| baseline dev score | 0.6412 |
| exploration best | 0.7098 (`r02-c2`) |
| finalist | `r02-c2` |
| confirmation on unseen split seeds | `confirmed_pass` [0.0668, 0.0705, 0.066] |
| delivered | `r02-c2` · dev score 0.7098 |
| sealed holdout score | 0.7099 |

## Cost

- LLM calls: 6 · requests: 0 · tokens: 0 · cost (USD, priced calls only): 0.0
- by role: `{"proposer": {"calls": 6, "input_tokens": 0, "output_tokens": 0}}`
- unknown (not reported by provider): `{"cost_usd": 0.0, "experiments": 0, "fits": 0, "llm_requests": 0, "llm_tokens": 0, "seconds": 0.0}`
- training jobs: 25 · estimator fits: 121 · training seconds: 82.0

## Process

- rounds: 6 · experiments: 12 (proposer 8, tool search 4) · failed: 0
- passed vs baseline: 12 · duplicates blocked: 0 · invalid rejected: 0 · empty rounds: 2
- hypothesis verdicts (vs declared comparator): `{"candidate_pass": 2, "not_met": 6}`
- direction changes by trigger: `{"agent": 0, "error": 0, "rule": 1}`

## Experiments

| id | origin | spec | dev score | Δ vs base | verdict | Δ vs prev best | hypothesis |
|---|---|---|---|---|---|---|---|
| `baseline` | baseline | logistic_regression(c=1.0, max_iter=500) | 0.6412 | – | – | – |  |
| `tool-01` | tool_search | logistic_regression(c=2.0, class_weight=balanced, max_iter=500) | 0.6716 | 0.0303 | candidate_pass | 0.0303 |  |
| `tool-02` | tool_search | hist_gradient_boosting(learning_rate=0.06, max_iter=200, max_leaf_nodes=63, min_samples_leaf=50) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.6482 | 0.0069 | candidate_pass | -0.0234 |  |
| `r01-c1` | proposer | random_forest(class_weight=balanced, min_samples_leaf=5, n_estimators=100) | 0.7089 | 0.0677 | candidate_pass | 0.0373 | A random_forest model may capture structure the current best misses. |
| `r01-c2` | proposer | hist_gradient_boosting(class_weight=balanced, learning_rate=0.1, max_iter=100, max_leaf_nodes=31, min_samples_leaf=20) | 0.6931 | 0.0518 | candidate_pass | -0.0158 | A hist_gradient_boosting model may capture structure the current best misses. |
| `r02-c1` | proposer | logistic_regression(c=1.0, class_weight=balanced, max_iter=500) | 0.6715 | 0.0303 | candidate_pass | -0.0374 | A logistic_regression model may capture structure the current best misses. |
| `r02-c2` | proposer | random_forest(class_weight=balanced, min_samples_leaf=5, n_estimators=100) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.7098 | 0.0685 | candidate_pass | 0.0009 | pdays uses 999.0 as a placeholder; an explicit flag may help. |
| `r03-c1` | proposer | logistic_regression(c=1.0, class_weight=balanced, max_iter=500) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.6717 | 0.0305 | candidate_pass | -0.0381 | A logistic_regression model may capture structure the current best misses. |
| `r03-c2` | proposer | hist_gradient_boosting(class_weight=balanced, learning_rate=0.1, max_iter=100, max_leaf_nodes=31, min_samples_leaf=20) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.6924 | 0.0512 | candidate_pass | -0.0174 | A hist_gradient_boosting model may capture structure the current best misses. |
| `tool-09` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.06, max_iter=60, max_leaf_nodes=63, min_samples_leaf=10) + drop_columns(emp.var.rate) | 0.6931 | 0.0518 | candidate_pass | -0.0167 |  |
| `tool-10` | tool_search | logistic_regression(c=10.0, class_weight=balanced, max_iter=500) + log1p(previous) | 0.6718 | 0.0306 | candidate_pass | -0.0380 |  |
| `r04-c1` | proposer | random_forest(class_weight=balanced, min_samples_leaf=10, n_estimators=100) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.7055 | 0.0643 | candidate_pass | -0.0043 | Tuning min_samples_leaf may trade bias and variance better. |
| `r04-c2` | proposer | random_forest(class_weight=balanced, min_samples_leaf=2, n_estimators=100) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.7073 | 0.0661 | candidate_pass | -0.0025 | Tuning min_samples_leaf may trade bias and variance better. |

## Evidence boundaries

- Every score, delta and verdict above is computed by the evaluator from real fits; proposals never write metrics.
- Verdicts are engineering thresholds (paired same-fold delta ≥ min_effect, then re-checked on unseen split seeds), not significance tests.
- The sealed holdout is not read during research; it is scored once after delivery is frozen (`budgetlab evaluate`).
- `scripted` proposals are deterministic rules for offline testing, not LLM output.
