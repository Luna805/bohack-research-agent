# Night Run Decisions

## D001: Offline-first A-layer implementation

- Decision: implement and verify the deterministic research engine before any model gateway work.
- Reason: the project API budget is explicitly zero, while real local ML training is authorized and required.
- Impact: PydanticAI live calls will not be made; B-layer status will be `blocked_external`.

## D002: Built-in breast cancer dataset for engineering smoke

- Decision: use `sklearn.datasets.load_breast_cancer` as the real binary-classification smoke dataset.
- Reason: it is locally available, legal to load without credentials, and explicitly allowed by the night-run instructions when Bank Marketing is unavailable.
- Impact: results prove the engine path, not Bank Marketing business validity or Kaggle performance.

## D003: Frozen uv environment plus pip-compatible export

- Decision: install public `uv`/`ruff` tooling, generate `uv.lock`, verify a fresh `.venv`, and export `requirements.lock` for the base runtime.
- Reason: the active environment allowed an early real fit, while the final deliverable still required a reproducible lock and lint evidence.
- Impact: the verified install command is `python -m uv sync --frozen --extra dev --extra llm`.

## D004: PydanticAI slim fixture path

- Decision: lock `pydantic-ai-slim==2.68.0` and validate the final nested `ProposalBatch` through its local `TestModel`.
- Reason: the slim package exposes the Agent API without installing every provider extra.
- Impact: the fixture proves framework/schema integration only, not a live provider result.
