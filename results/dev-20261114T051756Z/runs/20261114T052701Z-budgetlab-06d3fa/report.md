# BudgetLab run `20261114T052701Z-budgetlab-06d3fa`

- task: `adult` · system: `budgetlab` · proposals: `scripted`
- primary metric: `f1_macro` (development 5-fold CV); frozen min_effect = 0.0020
- stop reason: `no_valid_candidates` · wall time: 148.38 s
- code version: `e053b73`

## Result

| item | value |
|---|---|
| baseline dev score | 0.7792 |
| exploration best | 0.8147 (`tool-02`) |
| finalist | `tool-02` |
| confirmation on unseen split seeds | `confirmed_pass` [0.0322, 0.0339, 0.033] |
| delivered | `tool-02` · dev score 0.8147 |
| sealed holdout score | 0.8151 |

## Cost

- LLM calls: 4 · requests: 0 · tokens: 0 · cost (USD, priced calls only): 0.0
- by role: `{"proposer": {"calls": 4, "input_tokens": 0, "output_tokens": 0}}`
- unknown (not reported by provider): `{"cost_usd": 0.0, "experiments": 0, "fits": 0, "llm_requests": 0, "llm_tokens": 0, "seconds": 0.0}`
- training jobs: 21 · estimator fits: 101 · training seconds: 148.1

## Process

- rounds: 4 · experiments: 8 (proposer 4, tool search 4) · failed: 0
- passed vs baseline: 5 · duplicates blocked: 0 · invalid rejected: 0 · empty rounds: 2
- hypothesis verdicts (vs declared comparator): `{"not_met": 4}`
- direction changes by trigger: `{"agent": 0, "error": 0, "rule": 0}`

## Experiments

| id | origin | spec | dev score | Δ vs base | verdict | Δ vs prev best | hypothesis |
|---|---|---|---|---|---|---|---|
| `baseline` | baseline | logistic_regression(c=1.0, max_iter=500) | 0.7792 | – | – | – |  |
| `tool-01` | tool_search | logistic_regression(c=2.0, class_weight=balanced, max_iter=500) | 0.7688 | -0.0105 | not_met | -0.0105 |  |
| `tool-02` | tool_search | hist_gradient_boosting(learning_rate=0.06, max_iter=200, max_leaf_nodes=63, min_samples_leaf=50) + log1p(capital-loss) | 0.8147 | 0.0355 | candidate_pass | 0.0355 |  |
| `r01-c1` | proposer | hist_gradient_boosting(class_weight=balanced, learning_rate=0.06, max_iter=200, max_leaf_nodes=63, min_samples_leaf=50) + log1p(capital-loss) | 0.7970 | 0.0178 | candidate_pass | -0.0177 | Balanced class weights should raise minority-class F1 on an imbalanced task. |
| `r01-c2` | proposer | logistic_regression(c=1.0, class_weight=balanced, max_iter=500) + log1p(capital-loss) | 0.7684 | -0.0108 | not_met | -0.0463 | A logistic_regression model may capture structure the current best misses. |
| `r02-c1` | proposer | random_forest(class_weight=balanced, min_samples_leaf=5, n_estimators=100) + log1p(capital-loss) | 0.7820 | 0.0028 | candidate_pass | -0.0327 | A random_forest model may capture structure the current best misses. |
| `r02-c2` | proposer | hist_gradient_boosting(learning_rate=0.05, max_iter=200, max_leaf_nodes=63, min_samples_leaf=50) + log1p(capital-loss) | 0.8140 | 0.0348 | candidate_pass | -0.0007 | Tuning learning_rate, max_iter may trade bias and variance better. |
| `tool-07` | tool_search | random_forest(min_samples_leaf=1, n_estimators=60) + drop_columns(relationship) | 0.7853 | 0.0061 | candidate_pass | -0.0294 |  |
| `tool-08` | tool_search | logistic_regression(c=10.0, class_weight=balanced, max_iter=500) + log1p(capital-gain) | 0.7641 | -0.0152 | not_met | -0.0506 |  |

## Evidence boundaries

- Every score, delta and verdict above is computed by the evaluator from real fits; proposals never write metrics.
- Verdicts are engineering thresholds (paired same-fold delta ≥ min_effect, then re-checked on unseen split seeds), not significance tests.
- The sealed holdout is not read during research; it is scored once after delivery is frozen (`budgetlab evaluate`).
- `scripted` proposals are deterministic rules for offline testing, not LLM output.
