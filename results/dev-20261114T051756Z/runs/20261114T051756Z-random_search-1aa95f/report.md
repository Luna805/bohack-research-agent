# BudgetLab run `20261114T051756Z-random_search-1aa95f`

- task: `bank_marketing` · system: `random_search` · proposals: `none`
- primary metric: `f1_macro` (development 5-fold CV); frozen min_effect = 0.0020
- stop reason: `experiment_limit` · wall time: 96.39 s
- code version: `e053b73`

## Result

| item | value |
|---|---|
| baseline dev score | 0.6412 |
| exploration best | 0.7098 (`random-05`) |
| finalist | `random-05` |
| confirmation on unseen split seeds | `confirmed_pass` [0.0668, 0.0705, 0.066] |
| delivered | `random-05` · dev score 0.7098 |
| sealed holdout score | 0.7099 |

## Cost

- LLM calls: 0 · requests: 0 · tokens: 0 · cost (USD, priced calls only): 0.0
- by role: `{}`
- unknown (not reported by provider): `{"cost_usd": 0.0, "experiments": 0, "fits": 0, "llm_requests": 0, "llm_tokens": 0, "seconds": 0.0}`
- training jobs: 31 · estimator fits: 151 · training seconds: 96.0

## Process

- rounds: 0 · experiments: 18 (proposer 0, tool search 18) · failed: 0
- passed vs baseline: 16 · duplicates blocked: 0 · invalid rejected: 0 · empty rounds: 0
- hypothesis verdicts (vs declared comparator): `{}`
- direction changes by trigger: `{"agent": 0, "error": 0, "rule": 0}`

## Experiments

| id | origin | spec | dev score | Δ vs base | verdict | Δ vs prev best | hypothesis |
|---|---|---|---|---|---|---|---|
| `baseline` | baseline | logistic_regression(c=1.0, max_iter=500) | 0.6412 | – | – | – |  |
| `random-01` | tool_search | logistic_regression(c=2.0, class_weight=balanced, max_iter=500) | 0.6716 | 0.0303 | candidate_pass | 0.0303 |  |
| `random-02` | tool_search | hist_gradient_boosting(learning_rate=0.06, max_iter=200, max_leaf_nodes=63, min_samples_leaf=50) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.6482 | 0.0069 | candidate_pass | -0.0234 |  |
| `random-03` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.06, max_iter=60, max_leaf_nodes=63, min_samples_leaf=10) + drop_columns(emp.var.rate) | 0.6931 | 0.0518 | candidate_pass | 0.0215 |  |
| `random-04` | tool_search | logistic_regression(c=10.0, class_weight=balanced, max_iter=500) + log1p(previous) | 0.6718 | 0.0306 | candidate_pass | -0.0212 |  |
| `random-05` | tool_search | random_forest(class_weight=balanced, min_samples_leaf=5, n_estimators=100) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.7098 | 0.0685 | candidate_pass | 0.0167 |  |
| `random-06` | tool_search | random_forest(class_weight=balanced, max_depth=10, min_samples_leaf=1, n_estimators=60) | 0.6996 | 0.0584 | candidate_pass | -0.0101 |  |
| `random-07` | tool_search | random_forest(class_weight=balanced, max_depth=16, min_samples_leaf=1, n_estimators=100) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.7035 | 0.0622 | candidate_pass | -0.0063 |  |
| `random-08` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.2, max_iter=200, max_leaf_nodes=31, min_samples_leaf=20) | 0.6895 | 0.0483 | candidate_pass | -0.0203 |  |
| `random-09` | tool_search | random_forest(max_depth=6, min_samples_leaf=3, n_estimators=200) | 0.6142 | -0.0270 | not_met | -0.0956 |  |
| `random-10` | tool_search | hist_gradient_boosting(learning_rate=0.2, max_iter=100, max_leaf_nodes=15, min_samples_leaf=20) | 0.6521 | 0.0108 | candidate_pass | -0.0577 |  |
| `random-11` | tool_search | logistic_regression(c=10.0, class_weight=balanced, max_iter=500) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.6718 | 0.0305 | candidate_pass | -0.0380 |  |
| `random-12` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.1, max_iter=200, max_leaf_nodes=63, min_samples_leaf=50) | 0.6897 | 0.0485 | candidate_pass | -0.0201 |  |
| `random-13` | tool_search | random_forest(class_weight=balanced, max_depth=10, min_samples_leaf=5, n_estimators=60) + drop_columns(emp.var.rate) | 0.6982 | 0.0570 | candidate_pass | -0.0116 |  |
| `random-14` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.1, max_iter=60, max_leaf_nodes=31, min_samples_leaf=50) + sentinel_to_missing(pdays=999.0); missing_indicator(pdays) | 0.6902 | 0.0490 | candidate_pass | -0.0196 |  |
| `random-15` | tool_search | random_forest(max_depth=10, min_samples_leaf=10, n_estimators=100) | 0.6351 | -0.0062 | not_met | -0.0747 |  |
| `random-16` | tool_search | logistic_regression(c=10.0, class_weight=balanced, max_iter=500) | 0.6716 | 0.0304 | candidate_pass | -0.0382 |  |
| `random-17` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.2, max_iter=60, max_leaf_nodes=31, min_samples_leaf=50) + drop_columns(month) | 0.6880 | 0.0468 | candidate_pass | -0.0218 |  |
| `random-18` | tool_search | random_forest(class_weight=balanced, max_depth=6, min_samples_leaf=10, n_estimators=60) + drop_columns(marital) | 0.6788 | 0.0376 | candidate_pass | -0.0310 |  |

## Evidence boundaries

- Every score, delta and verdict above is computed by the evaluator from real fits; proposals never write metrics.
- Verdicts are engineering thresholds (paired same-fold delta ≥ min_effect, then re-checked on unseen split seeds), not significance tests.
- The sealed holdout is not read during research; it is scored once after delivery is frozen (`budgetlab evaluate`).
- `scripted` proposals are deterministic rules for offline testing, not LLM output.
