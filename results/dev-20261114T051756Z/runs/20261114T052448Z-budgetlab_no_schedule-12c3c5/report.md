# BudgetLab run `20261114T052448Z-budgetlab_no_schedule-12c3c5`

- task: `adult` · system: `budgetlab_no_schedule` · proposals: `scripted`
- primary metric: `f1_macro` (development 5-fold CV); frozen min_effect = 0.0020
- stop reason: `no_valid_candidates` · wall time: 133.49 s
- code version: `e053b73`

## Result

| item | value |
|---|---|
| baseline dev score | 0.7792 |
| exploration best | 0.7971 (`r03-c1`) |
| finalist | `r03-c1` |
| confirmation on unseen split seeds | `confirmed_pass` [0.017, 0.0173, 0.0154] |
| delivered | `r03-c1` · dev score 0.7971 |
| sealed holdout score | 0.7941 |

## Cost

- LLM calls: 5 · requests: 0 · tokens: 0 · cost (USD, priced calls only): 0.0
- by role: `{"proposer": {"calls": 5, "input_tokens": 0, "output_tokens": 0}}`
- unknown (not reported by provider): `{"cost_usd": 0.0, "experiments": 0, "fits": 0, "llm_requests": 0, "llm_tokens": 0, "seconds": 0.0}`
- training jobs: 19 · estimator fits: 91 · training seconds: 133.2

## Process

- rounds: 5 · experiments: 6 (proposer 6, tool search 0) · failed: 0
- passed vs baseline: 4 · duplicates blocked: 0 · invalid rejected: 0 · empty rounds: 2
- hypothesis verdicts (vs declared comparator): `{"candidate_pass": 2, "not_met": 4}`
- direction changes by trigger: `{"agent": 0, "error": 0, "rule": 0}`

## Experiments

| id | origin | spec | dev score | Δ vs base | verdict | Δ vs prev best | hypothesis |
|---|---|---|---|---|---|---|---|
| `baseline` | baseline | logistic_regression(c=1.0, max_iter=500) | 0.7792 | – | – | – |  |
| `r01-c1` | proposer | random_forest(class_weight=balanced, min_samples_leaf=5, n_estimators=100) | 0.7820 | 0.0028 | candidate_pass | 0.0028 | A random_forest model may capture structure the current best misses. |
| `r01-c2` | proposer | logistic_regression(c=1.0, class_weight=balanced, max_iter=500) | 0.7688 | -0.0104 | not_met | -0.0132 | Balanced class weights should raise minority-class F1 on an imbalanced task. |
| `r02-c1` | proposer | hist_gradient_boosting(class_weight=balanced, learning_rate=0.1, max_iter=100, max_leaf_nodes=31, min_samples_leaf=20) | 0.7958 | 0.0166 | candidate_pass | 0.0138 | A hist_gradient_boosting model may capture structure the current best misses. |
| `r02-c2` | proposer | random_forest(class_weight=balanced, min_samples_leaf=10, n_estimators=100) | 0.7752 | -0.0040 | not_met | -0.0206 | Tuning min_samples_leaf may trade bias and variance better. |
| `r03-c1` | proposer | hist_gradient_boosting(class_weight=balanced, learning_rate=0.05, max_iter=200, max_leaf_nodes=31, min_samples_leaf=20) | 0.7971 | 0.0178 | candidate_pass | 0.0012 | Tuning learning_rate, max_iter may trade bias and variance better. |
| `r03-c2` | proposer | hist_gradient_boosting(class_weight=balanced, learning_rate=0.1, max_iter=100, max_leaf_nodes=31, min_samples_leaf=50) | 0.7954 | 0.0162 | candidate_pass | -0.0016 | Tuning min_samples_leaf may trade bias and variance better. |

## Evidence boundaries

- Every score, delta and verdict above is computed by the evaluator from real fits; proposals never write metrics.
- Verdicts are engineering thresholds (paired same-fold delta ≥ min_effect, then re-checked on unseen split seeds), not significance tests.
- The sealed holdout is not read during research; it is scored once after delivery is frozen (`budgetlab evaluate`).
- `scripted` proposals are deterministic rules for offline testing, not LLM output.
