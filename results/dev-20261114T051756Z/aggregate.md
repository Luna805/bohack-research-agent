# Matrix `dev-20261114T051756Z`

Per task and system (mean ± sample std over repeats; ok runs only).

| task | system | n | baseline | best dev | delivered dev | holdout | LLM tokens | wall s | confirmed |
|---|---|---|---|---|---|---|---|---|---|
| adult | budgetlab | 1 | 0.7792 | 0.8147 | 0.8147 | 0.8151 | 0 | 148.4 | 1/1 |
| adult | budgetlab_no_schedule | 1 | 0.7792 | 0.7971 | 0.7971 | 0.7941 | 0 | 133.5 | 1/1 |
| adult | random_search | 1 | 0.7792 | 0.8154 | 0.8154 | 0.8143 | 0 | 163.9 | 1/1 |
| bank_marketing | budgetlab | 1 | 0.6412 | 0.7098 | 0.7098 | 0.7099 | 0 | 82.3 | 1/1 |
| bank_marketing | budgetlab_no_schedule | 1 | 0.6412 | 0.7098 | 0.7098 | 0.7099 | 0 | 68.7 | 1/1 |
| bank_marketing | random_search | 1 | 0.6412 | 0.7098 | 0.7098 | 0.7099 | 0 | 96.4 | 1/1 |

## Paired comparison against `random_search` (same task and repeat, same seeds)

W/T/L: holdout difference beyond the larger calibrated min_effect of the pair (engineering band, not a significance test). CI>0 / CI<0: pairs whose paired bootstrap 95% interval of the holdout difference lies entirely above / below zero (descriptive, same holdout rows for both systems).

| task | system | pairs | Δ holdout | W/T/L | CI>0 / CI<0 | LLM tokens | Δ wall s | Δ experiments | Δ holdout per 1k tokens |
|---|---|---|---|---|---|---|---|---|---|
| bank_marketing | budgetlab_no_schedule | 1 | +0.0000 | 0/1/0 | 0/0 of 1 | 0 | -27.7 | -10.0 | – |
| bank_marketing | budgetlab | 1 | +0.0000 | 0/1/0 | 0/0 of 1 | 0 | -14.1 | -6.0 | – |
| adult | budgetlab_no_schedule | 1 | -0.0202 | 0/0/1 | 0/1 of 1 | 0 | -30.4 | -12.0 | – |
| adult | budgetlab | 1 | +0.0008 | 0/1/0 | 0/0 of 1 | 0 | -15.5 | -10.0 | – |

## Cost efficiency (dev gain = delivered dev score - baseline dev score)

| task | system | runs | dev gain | holdout | LLM tokens | wall s | dev gain per 1k tokens | dev gain per minute |
|---|---|---|---|---|---|---|---|---|
| bank_marketing | random_search | 1 | +0.0685 | 0.7099 | 0 | 96.4 | – | +0.0427 |
| bank_marketing | budgetlab_no_schedule | 1 | +0.0685 | 0.7099 | 0 | 68.7 | – | +0.0599 |
| bank_marketing | budgetlab | 1 | +0.0685 | 0.7099 | 0 | 82.3 | – | +0.0500 |
| adult | random_search | 1 | +0.0362 | 0.8143 | 0 | 163.9 | – | +0.0133 |
| adult | budgetlab_no_schedule | 1 | +0.0178 | 0.7941 | 0 | 133.5 | – | +0.0080 |
| adult | budgetlab | 1 | +0.0355 | 0.8151 | 0 | 148.4 | – | +0.0143 |
