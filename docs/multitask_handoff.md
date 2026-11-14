# 多分类 + 回归任务支持 · 交接文档

> 作者：A（Yolo）+ Claude Code · 分支 `a/multitask` · 2026-11-14 冻结后
> 状态：**已实现并在新分支上通过测试，未合入 main**（正式矩阵的 `main` 一行没动）。
> 配套：开发日志 `docs/devlog/A-agent.md`；调研报告 `多任务类型支持-调研报告.md`。

## 0. 一句话结论

BudgetLab 原来只支持「表格二分类」。本次在 `a/multitask` 分支上把任务类型泛化为三种——`binary` / `multiclass` / `regression`——研究主循环（预算、账本、提案、裁决、冻结、holdout 评测）现在对三种类型都能跑通。二分类主路径行为保持不变。

## 1. 这是不是正式成绩？不是

- `benchmark-freeze` 已打、正式矩阵（Bank / Adult 二分类）已冻结在 `main` 上运行。**本次改动只在分支上，未碰 main，不在正式成绩里**，属于「加分项」的代码能力。
- 合并前必须：① 群里知会 B、C（跨了他们的文件归属）；② review 通过后再合 `main`。

## 2. 交付内容（按文件归属）

| 层 | 文件 | 归属 | 改动 |
|---|---|---|---|
| 契约 | `schemas.py` | B | `Metric` +`r2/rmse/mae`；`ModelFamily` +3 个回归器族；`TaskType`/`Direction`/`metric_direction()`；`task_type` 三值；放宽 `min_effect` 系列 `le=1` |
| 训练 | `pipeline.py` | B | logistic 改 `lbfgs`；3 个回归器分支；多分类/回归指标 |
| 裁决 | `evaluator.py` | B | 分数范围按指标判定；裁决/确认按 `direction` |
| 数据 | `data.py`、`worker.py` | B | `cv_splitter`（回归用 KFold）；回归目标保留 float |
| 状态 | `state.py` | B | `add()` 按方向选 best |
| 契约 | `contracts.py` | B | 冻结 `task_type` + `direction` |
| 搜索 | `search.py` | B | 回归器采样 + 回归基线（Ridge） |
| 主循环 | `controller.py` | B | 透传 `task_type`/`direction` |
| 画像 | `profile.py` | B | 按 task_type 给 `positive_rate`/`target_mean`/`class_share` |
| 经验库 | `memory/*.py` | B | 非二分类回退，避免 KeyError |
| holdout | `evaluation/__init__.py` | C | 多分类/回归指标 + 按 task_type 读入/输出 |
| 任务 | `tasks/__init__.py`、`cards/iris.yaml`、`cards/diabetes.yaml` | C | `TaskDefinition.task_type` + 两个离线内置任务 |
| 提案 | `proposers.py`、`agents/protocol_agent.py` | A | 回归器合法空间 + 上下文方向/任务类型 |
| 配置 | `configs/iris.yaml`、`configs/diabetes.yaml` | 新 | 两个 demo 配置 |
| 测试 | `tests/test_multitask.py` | 新 | 8 个离线单测 |

## 3. 怎么跑（离线，不联网、不花钱）

```bash
# 多分类（iris，3 类，macro-F1）
uv run python -m budgetlab.cli prepare --task iris
uv run python -m budgetlab.cli research --config configs/iris.yaml --system budgetlab --proposer scripted

# 回归（diabetes，连续值，R²）
uv run python -m budgetlab.cli prepare --task diabetes
uv run python -m budgetlab.cli research --config configs/diabetes.yaml --system budgetlab --proposer scripted
```

跑完后用 `python -m budgetlab.cli evaluate --run-id <RUN_ID>` 做一次性 holdout 评测（每个 run 只能评一次）。

> 两个数据集都是 scikit-learn 内置（`load_iris` / `load_diabetes`），不走网络，和 `breast_cancer` 冒烟同款。

## 4. 关键设计（四件事，对应调研报告 §5）

1. **指标方向**：`metric_direction(metric)` —— `r2/f1_macro/accuracy/roc_auc` 是 maximize，`rmse/mae` 是 minimize。方向写进 `DecisionPolicy.direction` 并在契约冻结，裁决、选 best、确认、最终排序全按它来。
2. **模型族**：新增 `ridge` / `random_forest_regressor` / `hist_gradient_boosting_regressor` 三个回归器族，与分类器族并列在 `ModelFamily` 联合类型里；`build_pipeline` 按 family 选分类器还是回归器（不另传 task_type）。
3. **目标编码**：分类目标在 `load_raw` 里已经 label 编码成 0/1 或 0..K-1；回归目标保留 float。`load_development`/holdout 读入按 task_type 决定是否 `.astype(int)`。
4. **切分**：`cv_splitter(task_type, ...)` —— 回归用 `KFold`（无分层），其余用 `StratifiedKFold`；`prepare_task` 的 holdout 切分同样对回归跳过 `stratify`。

## 5. 验证结果（如实）

- `pytest`：`tests/test_multitask.py` 8 passed；`test_evaluator.py` 13 passed（旧测试「分数必须 0–1」改为**按指标判定**）；全量测试其余不动。`ruff check .` 与 `ruff format --check` 全过。
- 端到端（脚本化提案）：`diabetes` → 基线 R²=0.461，holdout R²=0.571（CI [0.449, 0.654]）；`iris` → holdout macro-F1=1.0。两者都因「无候选超过基线 min_effect」走了 `not_required_no_candidate` 交付基线——这符合饱和基准的预期，说明裁决/确认/交付链路跑通，不是说它「研究出了增益」。

## 6. 已知限制（没测过的不写进 README/PPT）

1. **效应量归一化是第一版**：`noise_floor = stdev(scores)`、`min_effect = max(floor, noise_floor)` 对 [0,1] 指标和 R²（近似有界）成立；对 RMSE/MAE（有量纲、minimize）只在同一数据尺度下成立，**跨任务不可比**。真正尺度无关的「相对基线改进」留到提交后。
2. **CSV 上传仍是二分类**（`csv_task.py` 未改）：多分类/回归只通过内置任务卡进入。上传页要支持多任务需 C 扩展 `csv_task` + D 改协议卡 UI。
3. **`predicted_metric_delta` 仍限 [-1,1]**：只是提案者的自评、不参与裁决，回归时可能表达不了大 delta，未改。
4. **经验库（memory）仍是分类专用**：非二分类任务开了 memory 只是不崩（回退 0.5），不会正确匹配。
5. **多分类的 roc_auc holdout** 未做（多分类 demo 用 macro-F1/accuracy）；holdout 的 `y_score` 列只对二分类有「正类分数」。

## 7. 合并前要做的事

1. 群里知会 B（改了他 12 个文件）和 C（改了他 `evaluation/`、`tasks/`），按 `TEAM.md` 第 2 节流程 review。
2. CI 在 `a/multitask` 上跑绿后再合 `main`；合完删分支。
3. 是否进正式 README/PPT，等协调人拍板——按规范「没测过的能力不写」，目前只在 `iris`/`diabetes` 上验证过脚本化提案，**还没跑真实 LLM 提案**。

## 8. 下一步

- 回归的尺度无关效应量（`1 - RMSE_candidate/RMSE_baseline` 或 R² delta）作为独立改动。
- CSV 上传多任务（C）+ 协议卡 UI（D）。
- 真实 LLM 在 iris/diabetes 上跑一轮，看协议 Agent 是否会选错「分类 vs 回归」指标。
