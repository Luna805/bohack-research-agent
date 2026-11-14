# BudgetLab

BudgetLab is a deterministic, auditable ML research controller. A proposer may suggest only controlled experiment specifications; Python code owns data boundaries, real training, metrics, budgets, confirmation, delivery freezing, and replay.

The night smoke uses the real `sklearn.datasets.load_breast_cancer` binary dataset as an engineering substitute. It does not claim Bank Marketing or Kaggle validity. Live model calls are disabled because the project API budget is zero.

## Install

```powershell
python -m uv sync --frozen --extra dev --extra llm
```

The night run generated `uv.lock` and verified a clean `.venv` install. `requirements.lock` is also exported for the base runtime when `uv` is unavailable.

## Command surface

```powershell
python -m budgetlab.cli --help
python -m budgetlab.cli doctor --config configs/night_smoke.yaml
python -m budgetlab.cli research --config configs/night_smoke.yaml --system random_search
python -m budgetlab.cli research --config configs/night_smoke.yaml --system scripted_smoke
python -m budgetlab.cli reproduce --run-id ACTUAL_RUN_ID
python -m budgetlab.cli replay --run-id ACTUAL_RUN_ID
```

Runs are written under `runs/`. Each run contains a protocol, fixed split manifest, calibration report, frozen contract, append-only event ledger, budget state, per-experiment evidence, a full-development refit model, frozen delivery manifest, and Markdown report. Replay reads only saved events and starts zero fits and zero model requests.

## Evidence labels

- `random_search`: deterministic zero-token sampler plus real sklearn fits.
- `scripted`: strict `ProposalBatch` fixture used to test two feedback rounds plus real sklearn fits. It is not a real LLM result.
- `live_api`: unavailable unless a user grants explicit positive API limits and provides valid configuration.

## Isolation limit

Each training job runs in a dedicated child process with a hard timeout and one-thread settings. This is process control, not a verified OS security sandbox. Hidden competition data is not part of this repository or smoke path.
