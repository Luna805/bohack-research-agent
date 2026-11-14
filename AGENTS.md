# AGENTS.md — BudgetLab 开发规范（人和 AI 代理共用）

BudgetLab 是一个预算感知、证据约束的表格分类 Research Agent：LLM 每轮提出两个受控实验假设，其余由程序负责，包括训练、指标、裁决、预算、停止、确认、冻结交付和 holdout 评测。

- 当前进度、分工和待办：`docs/HANDOFF.md`（开始工作前先读）
- 设计依据：`BoHack2026_Research_Agent_最终方案_v3.md`
- 提交截止：2026-11-15 08:00（北京时间）

## 常用命令

```bash
uv sync --frozen --extra dev --extra llm
python -m budgetlab.cli prepare --task bank_marketing
python -m budgetlab.cli research --config configs/bank_marketing.yaml --system budgetlab --proposer scripted
python -m budgetlab.cli evaluate --run-id <RUN_ID>      # 每个 run 只能评一次
python -m pytest -q
ruff check . && ruff format --check budgetlab tests
```

## 不能破坏的约束

1. **LLM 只提案**。指标、裁决（`candidate_pass` / `not_met` / `confirmed_pass`）、晋级和停止都由程序计算；LLM 的输出类型里不能出现这些字段。
2. **holdout 只在 `budgetlab/evaluation/` 里读**。研究代码只用 `load_development()`；不要打开或打印 `data/sealed/` 下的文件。
3. **所有资源都走预算**。训练经过 `Runner.execute`；LLM 调用必须经过 `controller.metered_call`。没有返回 usage 的失败请求记为 unknown，不能记成 0。
4. **契约在第一次提案前冻结**（`contract.json`）。之后不能修改 `min_effect`、切分、合法列和预算。
5. **字段可用性只看场景卡**（`budgetlab/tasks/cards/*.yaml`）。不要在代码里硬编码"删掉某列"这类规则。
6. **不能静默改实验**。规格不合法就拒绝并给出原因，不能偷偷降级或改参数后再跑。
7. **每个结论都要能回溯**。新产物用 `atomic_write_json` 写入，并追加一条 ledger 事件。
8. **标注要诚实**。`scripted` 不能说成 LLM；没测过的能力不写进 README 和 PPT；数字只取自 `summary.json` / `final_evaluation.json`。

## 常见改动的检查清单

- **新增特征动作**要同时改 5 处：`schemas.py` 的联合类型 → `contracts.validate_experiment_spec` → `pipeline.apply_feature_actions` → `search.SpecSampler._actions` → `proposers.build_context` 的 `legal_space`，最后补测试。
- **新增任务**：在 `tasks/__init__.py` 加 `TaskDefinition` 和 loader，写 `cards/<task>.yaml`（每个字段都要有 `availability`），再执行 `prepare`。
- **改循环策略或预算**：改 `configs/*.yaml`，不要改代码里的默认值。

## 代码与测试

- Python ≥ 3.11，带类型注解；代码、注释和日志用英文，文档用中文。
- ruff 行宽 100；提交前必须跑 `pytest -q` 和 `ruff check .`。
- 测试不能联网，也不能依赖 API Key。LLM 相关测试用 Pydantic AI 的 `FunctionModel`（参考 `tests/test_controller_integration.py`）；数据用 `data_root` fixture。
- CI（`.github/workflows/ci.yml`）会在每次 push 时于 Ubuntu 和 Windows 上跑 lint 和测试；CI 是红的就不要合进 `main`。修改 `.github/workflows/` 需要带 `workflow` 权限的 token。

## Git 与协作

- 在短分支上开发：`<名字>/<主题>`，例如 `luna/benchmark`。合并前先 `git pull --rebase origin main`，合进 `main` 后删除分支。`main` 必须始终能跑演示。
- 小步提交，提交信息用英文祈使句（例如 `Add benchmark runner`）。禁止 `push --force` 到 `main`。
- 不要提交 `data/`、`runs/`、`.env`、`.venv/`；不要提交任何密钥。
- 按文件分工（见 HANDOFF 第 4 节）。要改别人负责的文件，先在群里说一声。
- 正式对照矩阵开跑前，在当时的提交上打 tag `benchmark-freeze`；之后代码和配置不再改动。每个 run 的 `run_config.json` 会自动记录 git 提交号和是否有未提交的改动。
- 正式结果只在一台机器上跑；跑完只把精简结果（`summary.json`、`final_evaluation.json`、`report.md`）复制到 `results/<run_id>/` 并提交，不提交模型文件。

## 结束一次工作时

1. 在 `docs/HANDOFF.md` 的"开发日志"里追加一条：时间、谁（人或代理）、做了什么、怎么验证的（命令、run_id）、遇到的问题、下一步。
2. 进度表或待办状态有变化，同步更新 HANDOFF 第 1、4 节。

## 对 AI 代理的额外要求

- 只有在配置里 LLM 预算为正数、并且用户明确要求时，才能发真实 LLM 请求；不要读取或打印 `.env` 里的值。
- 不要伪造或手填任何指标；跑不出来就如实写"未完成"。
- 没有用户要求时不要提交或推送；推送前确认 CI 能通过。
