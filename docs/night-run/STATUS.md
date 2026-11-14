# Night Run Status

- started_at: 2026-11-14T00:54:54+08:00
- deadline_at: 2026-11-14T06:54:54+08:00
- validation_handoff_at: 2026-11-14T06:24:54+08:00
- completed_at: 2026-11-14T01:13:44+08:00
- current_stage: completed early after N08
- last_verified_at: 2026-11-14T01:13:44+08:00
- accepted_limits: API budget USD 0; single agent; <=400 estimator fit attempts; <=90 fits and <=20 training jobs per smoke; one training process/thread; <=120 seconds per job; no commit or push
- retained_product_fits_attempted: 72 across two research runs
- fixed_spec_reproduction_fits: 1
- estimated_total_actual_fits_including_three_full_test_runs: 121
- conservative_test_timeout_unknown_fit_units: 6 in temporary pytest ledgers
- known_api_cost: USD 0
- actual_external_model_requests: 0
- fixture_model_requests: 2 local PydanticAI TestModel calls
- unknown_api_cost: none
- stage_status:
  - N00: passed
  - N01: passed
  - N02: passed
  - N03: passed
  - N04: passed
  - N05: passed
  - N06: gateway_and_fixture_passed; live_api=blocked_external
  - N07: passed
  - N08: passed
- last_validation: frozen sync passed; Ruff passed; 14 tests passed; scripted and random 5-fold smokes passed; reproduce passed; replay started zero fits/requests and left budget hash unchanged; git diff check passed; secret scan found no matches
- next_action: daytime owner may add authorized live provider and formal dataset evidence; no night-run action remains

## Preserved Startup State

The following pre-existing working-tree changes were left intact and were not staged, committed, pushed, restored, or overwritten:

- deleted: the original PydanticAI system-design Markdown file reported by Git
- untracked: `BoHack2026_BudgetLab_详细实施方案_v3.0.md`
- untracked: `BoHack2026_Research_Agent_最终方案_v3.md`
- untracked: `NIGHT_RUN_PROMPTS.md`
- untracked: `NIGHT_RUN_TASKS.md`

