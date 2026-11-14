# Matrix `dev-20261114T030336Z`

Per task and system (mean ± sample std over repeats; ok runs only).

| task | system | n | baseline | best dev | delivered dev | holdout | LLM tokens | wall s | confirmed |
|---|---|---|---|---|---|---|---|---|---|
| bank_marketing | budgetlab | 1 | 0.6412 | 0.7098 | 0.7098 | 0.7099 | 0 | 82.3 | 1/1 |
| bank_marketing | budgetlab_no_schedule | 1 | 0.6412 | 0.7098 | 0.7098 | 0.7099 | 0 | 68.8 | 1/1 |
| bank_marketing | random_search | 1 | 0.6412 | 0.7098 | 0.7098 | 0.7099 | 0 | 96.7 | 1/1 |

## Paired comparison against `random_search` (same task and repeat, same seeds)

W/T/L: holdout difference beyond the larger calibrated min_effect of the pair (engineering band, not a significance test).

| task | system | pairs | Δ holdout | W/T/L | LLM tokens | Δ wall s | Δ experiments | Δ holdout per 1k tokens |
|---|---|---|---|---|---|---|---|---|
| bank_marketing | budgetlab_no_schedule | 1 | +0.0000 | 0/1/0 | 0 | -27.9 | -10.0 | – |
| bank_marketing | budgetlab | 1 | +0.0000 | 0/1/0 | 0 | -14.4 | -6.0 | – |

## Cost efficiency (dev gain = delivered dev score - baseline dev score)

| task | system | runs | dev gain | holdout | LLM tokens | wall s | dev gain per 1k tokens | dev gain per minute |
|---|---|---|---|---|---|---|---|---|
| bank_marketing | random_search | 1 | +0.0685 | 0.7099 | 0 | 96.7 | – | +0.0425 |
| bank_marketing | budgetlab_no_schedule | 1 | +0.0685 | 0.7099 | 0 | 68.8 | – | +0.0598 |
| bank_marketing | budgetlab | 1 | +0.0685 | 0.7099 | 0 | 82.3 | – | +0.0500 |
