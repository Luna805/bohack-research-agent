# Night Run Blockers

## B001: Live LLM validation is not authorized

- Status: blocked_external
- Evidence: the user set the new-project API budget to 0 and did not grant the optional paid authorization in `NIGHT_RUN_PROMPTS.md` section 2.
- Attempts: none; no credential values were read or printed.
- Alternative route: implement a zero-credential gateway boundary and fixture tests; use `ScriptedProposer` only for explicitly labeled offline controller tests.
- Daytime unblock: provide explicit project API budget, model/provider configuration, verified pricing, and usable credentials.

## B002: uv was absent at startup (resolved)

- Status: resolved
- Evidence: `uv --version` returned command-not-found at 2026-11-14T00:54:54+08:00.
- Resolution: installed public `uv==0.13.8` and `ruff==0.17.5`, generated `uv.lock`, and completed a frozen `.venv` sync.

## B003: Formal Bank/Kaggle evidence is unavailable

- Status: blocked_external for domain/competition claims, not for the A-layer engine.
- Evidence: no Kaggle login, rule acceptance, competition data, or hidden grader was used.
- Alternative route: the allowed sklearn breast-cancer dataset was used for real engineering smoke runs.
- Daytime unblock: prepare the approved dataset and prediction-time feature policy under the user's competition account.

## B004: OS sandbox isolation is not verified

- Status: deferred
- Evidence: training jobs run in child processes with timeouts and one-thread limits, but no separate OS identity/container/mount boundary was tested.
- Impact: do not describe the application-level path boundary as a security sandbox.
