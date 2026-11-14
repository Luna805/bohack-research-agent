# BudgetLab run `20261114T052204Z-random_search-5faa61`

- task: `adult` · system: `random_search` · proposals: `none`
- primary metric: `f1_macro` (development 5-fold CV); frozen min_effect = 0.0020
- stop reason: `experiment_limit` · wall time: 163.89 s
- code version: `e053b73`

## Result

| item | value |
|---|---|
| baseline dev score | 0.7792 |
| exploration best | 0.8154 (`random-10`) |
| finalist | `random-10` |
| confirmation on unseen split seeds | `confirmed_pass` [0.0337, 0.0356, 0.0338] |
| delivered | `random-10` · dev score 0.8154 |
| sealed holdout score | 0.8143 |

## Cost

- LLM calls: 0 · requests: 0 · tokens: 0 · cost (USD, priced calls only): 0.0
- by role: `{}`
- unknown (not reported by provider): `{"cost_usd": 0.0, "experiments": 0, "fits": 0, "llm_requests": 0, "llm_tokens": 0, "seconds": 0.0}`
- training jobs: 31 · estimator fits: 151 · training seconds: 163.5

## Process

- rounds: 0 · experiments: 18 (proposer 0, tool search 18) · failed: 0
- passed vs baseline: 8 · duplicates blocked: 0 · invalid rejected: 0 · empty rounds: 0
- hypothesis verdicts (vs declared comparator): `{}`
- direction changes by trigger: `{"agent": 0, "error": 0, "rule": 0}`

## Experiments

| id | origin | spec | dev score | Δ vs base | verdict | Δ vs prev best | hypothesis |
|---|---|---|---|---|---|---|---|
| `baseline` | baseline | logistic_regression(c=1.0, max_iter=500) | 0.7792 | – | – | – |  |
| `random-01` | tool_search | logistic_regression(c=2.0, class_weight=balanced, max_iter=500) | 0.7688 | -0.0105 | not_met | -0.0105 |  |
| `random-02` | tool_search | hist_gradient_boosting(learning_rate=0.06, max_iter=200, max_leaf_nodes=63, min_samples_leaf=50) + log1p(capital-loss) | 0.8147 | 0.0355 | candidate_pass | 0.0355 |  |
| `random-03` | tool_search | random_forest(min_samples_leaf=1, n_estimators=60) + drop_columns(relationship) | 0.7853 | 0.0061 | candidate_pass | -0.0294 |  |
| `random-04` | tool_search | logistic_regression(c=10.0, class_weight=balanced, max_iter=500) + log1p(capital-gain) | 0.7641 | -0.0152 | not_met | -0.0506 |  |
| `random-05` | tool_search | random_forest(class_weight=balanced, min_samples_leaf=5, n_estimators=100) + log1p(capital-gain) | 0.7820 | 0.0028 | candidate_pass | -0.0327 |  |
| `random-06` | tool_search | random_forest(max_depth=10, min_samples_leaf=1, n_estimators=200) | 0.7785 | -0.0007 | not_met | -0.0362 |  |
| `random-07` | tool_search | random_forest(class_weight=balanced, max_depth=16, min_samples_leaf=1, n_estimators=100) + log1p(fnlwgt) | 0.7783 | -0.0009 | not_met | -0.0364 |  |
| `random-08` | tool_search | random_forest(class_weight=balanced, max_depth=10, min_samples_leaf=10, n_estimators=100) | 0.7548 | -0.0244 | not_met | -0.0599 |  |
| `random-09` | tool_search | random_forest(max_depth=6, min_samples_leaf=3, n_estimators=200) | 0.7472 | -0.0320 | not_met | -0.0675 |  |
| `random-10` | tool_search | hist_gradient_boosting(learning_rate=0.2, max_iter=100, max_leaf_nodes=15, min_samples_leaf=20) | 0.8154 | 0.0362 | candidate_pass | 0.0007 |  |
| `random-11` | tool_search | logistic_regression(c=10.0, class_weight=balanced, max_iter=500) + log1p(capital-loss) | 0.7684 | -0.0108 | not_met | -0.0470 |  |
| `random-12` | tool_search | random_forest(class_weight=balanced, max_depth=16, min_samples_leaf=10, n_estimators=200) + log1p(capital-gain) | 0.7689 | -0.0103 | not_met | -0.0465 |  |
| `random-13` | tool_search | logistic_regression(c=0.2, max_iter=500) | 0.7789 | -0.0003 | not_met | -0.0365 |  |
| `random-14` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.2, max_iter=100, max_leaf_nodes=15, min_samples_leaf=20) | 0.7956 | 0.0164 | candidate_pass | -0.0198 |  |
| `random-15` | tool_search | random_forest(class_weight=balanced, min_samples_leaf=5, n_estimators=100) + drop_columns(relationship) | 0.7816 | 0.0024 | candidate_pass | -0.0338 |  |
| `random-16` | tool_search | hist_gradient_boosting(class_weight=balanced, learning_rate=0.2, max_iter=60, max_leaf_nodes=31, min_samples_leaf=50) + drop_columns(capital-gain) | 0.7684 | -0.0109 | not_met | -0.0471 |  |
| `random-17` | tool_search | random_forest(class_weight=balanced, min_samples_leaf=3, n_estimators=100) | 0.7893 | 0.0100 | candidate_pass | -0.0262 |  |
| `random-18` | tool_search | random_forest(min_samples_leaf=1, n_estimators=100) + drop_columns(sex) | 0.7882 | 0.0090 | candidate_pass | -0.0272 |  |

## Evidence boundaries

- Every score, delta and verdict above is computed by the evaluator from real fits; proposals never write metrics.
- Verdicts are engineering thresholds (paired same-fold delta ≥ min_effect, then re-checked on unseen split seeds), not significance tests.
- The sealed holdout is not read during research; it is scored once after delivery is frozen (`budgetlab evaluate`).
- `scripted` proposals are deterministic rules for offline testing, not LLM output.
