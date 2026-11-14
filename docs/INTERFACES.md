# BudgetLab 模块接口规范

> 角色之间只通过下面这些接口对接。接口的负责人可以改实现，但**只能加字段，不能改名或删字段**。破坏性修改要先在群里说，同时提升版本号并更新本文（见 TEAM.md 6.2）。
> 代码是事实来源；本文和代码不一致时，以代码为准，并立刻修正本文。

| # | 接口 | 提供方 | 使用方 |
|---|---|---|---|
| 1 | run 目录格式 | B | C、D |
| 2 | `run_research` 与评测 API | B / C | C |
| 3 | Proposer / Critic 协议与上下文 | A（实现）/ B（调用） | B |
| 4 | 任务适配器与场景卡 | C | B、A |
| 5 | `results/` 对照结果格式 | C | D |
| 6 | 经验库（P1） | B | A |
| 7 | 配置文件分段 | 各段负责人 | 全员 |
| 8 | 对话式研究页的对接（协议草稿、CSV 任务、后台运行、问答） | A / C / D | D |

---

## 1. run 目录格式（B 提供）

路径：`runs/<run_id>/`，其中 `run_id = <UTC时间>-<system>-<6位随机>`。run 目录一旦写完就不再修改，`final_evaluation.json` 除外（由评测写入，且只写一次）。

| 文件                                                                                                                                                                                      | 内容                                 | 主要读者    |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- | ------- |
| `summary.json`                                                                                                                                                                          | 一次 run 的全部汇总，**界面和表格都从这里取数**       | C、D     |
| `final_evaluation.json`                                                                                                                                                                 | holdout 一次性评测结果                    | C、D     |
| `report.md`                                                                                                                                                                             | 人读报告（D 负责模板）                       | 评委      |
| `events.jsonl`                                                                                                                                                                          | 单写者事件流，`seq` 连续                    | D（轨迹回放） |
| `experiments/<id>.json`                                                                                                                                                                 | 单个实验的规格、结果和全部裁决                    | D（证据链）  |
| `rounds/round-NN.json`                                                                                                                                                                  | 每轮的提案，选中、拒绝、未运行及原因，触发来源            | D（轨迹）   |
| `llm_calls.jsonl`                                                                                                                                                                       | 每次 LLM 调用的预留、用量、未知项、上下文和输出引用       | C、D     |
| `llm/<role>-rNN.{context,output}.json`                                                                                                                                                  | 原样保存的上下文和输出                        | D（证据链）  |
| `run_config.json`                                                                                                                                                                       | 配置、系统、提案来源、data_root、**git 版本、环境** | C       |
| `contract.json`、`protocol.json`、`calibration.json`、`confirmation.json`、`confirmation/split-<seed>.json`、`eda.json`、`budget.json`、`scenario_card.json`、`split_manifest.json`、`delivery/` | 契约与证据                              | 审计      |

### 1.1 `summary.json`（`summary_version: 1`）

```text
summary_version, run_id, system, task_id, code_version, git, proposal_source,
primary_metric, min_effect, baseline_score, exploration_best_id, exploration_best_score,
finalist_id, confirmation_status, confirmation_deltas, delivered_experiment_id,
delivered_spec_hash, delivered_dev_score, model_ref, stop_reason, wall_seconds,
counts{rounds, experiments, proposer_experiments, tool_search_experiments, failed_experiments,
       passed_vs_baseline, duplicates_blocked, invalid_rejected, empty_rounds,
       direction_changes{agent, rule, error}, hypothesis_verdicts{<status>: n}},
llm{calls, by_role{<role>: {calls, input_tokens, output_tokens}}, requests, tokens, cost_usd, unknown{...}},
trajectory[{experiment_id, origin, round, mean_score, best_score_after, elapsed_seconds, llm_tokens_so_far}],
experiments[{id, origin, round, spec, status, mean_score, fold_std, delta_vs_baseline,
             baseline_verdict, delta_vs_previous_best, seconds, hypothesis?, hypothesis_verdict?,
             hypothesis_comparator?, delta_vs_hypothesis_comparator?, invalid_reason?, error?}],
budget{limits, used, reserved, unknown, tail_reserve, reservations}
```

各字段的取值：
- `system` ∈ `random_search` | `budgetlab_no_schedule` | `budgetlab`
- `proposal_source` ∈ `none` | `scripted` | `llm`
- `origin` ∈ `baseline` | `proposer` | `tool_search`
- 裁决 ∈ `candidate_pass` | `not_met` | `invalid`；确认 ∈ `confirmed_pass` | `not_met` | `inconclusive` | `not_required_no_candidate`
- `stop_reason` ∈ `max_rounds` | `diminishing_returns` | `no_valid_candidates` | `budget_exhausted` | `llm_budget_exhausted` | `target_reached` | `experiment_limit` | `space_exhausted`
- `code_version` 形如 `0f1188f` 或 `0f1188f-dirty`。**正式结果必须是非 dirty 的版本。**

### 1.2 `final_evaluation.json`

`run_id, metric, holdout_score, holdout_rows, development_cv_score, dev_minus_holdout, delivered_experiment_id, model_hash, evaluated_at`

### 1.3 `events.jsonl`

每行的字段：`seq, event_id, timestamp, run_id, action_id, event_type, artifact_ref, reason_code, details`。现有的 `event_type`：

`run_created, protocol_accepted, profile_written, baseline_completed, calibration_completed, contract_frozen, budget_reserved, budget_settled, budget_released, experiment_started, experiment_completed, experiment_failed, evaluation_recorded, tool_search_started, tool_search_completed, llm_call_started, llm_call_completed, llm_call_failed, direction_changed, candidate_rejected, candidate_selected, stop_decided, confirmation_split_invalid, confirmation_completed, refit_completed, refit_failed, delivery_frozen, run_terminal, final_evaluation_recorded`

新增事件类型可以，但不要改已有类型的含义。

## 2. 运行与评测 API

```python
# B：budgetlab/controller.py
SYSTEMS = ("random_search", "budgetlab_no_schedule", "budgetlab")
run_research(config: dict, system: str, runs_root: Path = Path("runs"),
             data_root: Path = Path("data"), *, proposer=None, critic=None,
             proposer_kind: str | None = None) -> dict   # 返回 summary.json 的内容
reproduce_run(run_id: str, runs_root: Path) -> dict
replay_run(run_id: str, runs_root: Path) -> dict          # 0 次训练，0 次请求

# C：budgetlab/evaluation/__init__.py
evaluate_frozen_run(run_id: str, runs_root: Path) -> dict  # 写 final_evaluation.json；第二次调用报错
```

约定：
- `run_research` 是同步调用，每次生成一个新的 run 目录，不会覆盖已有目录。
- 训练会占用 CPU，C 的批量脚本要**串行**调用，不要多进程并发跑 run，否则会污染耗时对比。
- `proposer` 和 `critic` 可以直接传入对象（测试用）；不传时按 `proposer_kind` 或配置里的 `proposer` 构造（`scripted` 或 `llm`）。

## 3. Proposer / Critic 协议（A 实现，B 调用）

```python
class Proposer(Protocol):          # budgetlab/proposers.py
    source: str                    # "scripted" | "llm"
    def estimate(self, context: dict) -> ResourceVector: ...   # 纯函数；调用前用来预留预算
    def propose(self, context: dict) -> CallOutcome: ...       # 绝不抛异常；失败时 output=None、error 填写原因

class Critic(Protocol):
    source: str
    def estimate(self, context: dict) -> ResourceVector: ...
    def review(self, context: dict) -> CallOutcome: ...        # output 是 CriticAdvice 或 None

@dataclass
class CallOutcome:
    output: ProposalBatch | CriticAdvice | None
    usage: ResourceVector     # 实际消耗：llm_tokens / llm_requests / cost_usd
    unknown: ResourceVector   # 拿不到用量的部分（按保守估计记，不能记成 0）
    details: dict             # model, output_mode, usage_source, input_tokens, output_tokens, requests, ...
    error: str | None
```

职责边界：
- **预算的预留和结算只由 B 的 `controller.metered_call` 做**。A 的代码不能直接碰 `Budget`。
- **输出类型是 `schemas.ProposalBatch`**：每次正好 2 个候选，每个候选包含 `Hypothesis` 和 `ExperimentSpec`。要改它需要 B 同意，因为它是共享 Schema。
- B 的程序负责筛查：合法列、对照实验是否存在、规格是否重复、证据引用是否有效。A 不需要重复做这些检查，但应该在提示词里减少这类错误。
- **上下文由 A 的 `build_context()` 生成**。它目前的键：`mode, task, legal_space, data_profile, excluded_columns, decision_rule, baseline_id, best_id, experiments, valid_evidence_refs, controller_feedback, critic_advice, progress, budget_remaining`。A 可以增删这些键，因为只有 LLM 读它们；B 只负责把 `ResearchState` 传进来。上下文里不能出现 holdout 的任何信息。

## 4. 任务适配器与场景卡（C 提供）

```python
# budgetlab/tasks/__init__.py
TaskDefinition(task_id, target_column, primary_metric, holdout_fraction, holdout_seed,
               load_raw: Callable[[Path], tuple[pd.DataFrame, pd.Series]])  # 目标列编码为 0/1
TASKS: dict[str, TaskDefinition]
get_task(task_id) -> TaskDefinition
approved_features(card, columns) -> tuple[str, ...]

# budgetlab/data.py
prepare_task(task_id, data_root, *, force=False) -> manifest dict   # 写 prepared/ 和 sealed/
load_development(task_id, data_root) -> DatasetBundle                # 只读开发集
```

场景卡 `budgetlab/tasks/cards/<task_id>.yaml` 的必填字段：

```yaml
task_id: ...
title: ...
business_question: ...
prediction_time: ...          # 预测发生在什么时点
target: {column: ..., positive_label: ...}
fields:                       # 每一列都要列出，或者用 default_availability 统一指定
  - {name: ..., type: numeric|categorical|text, availability: available|post_outcome|identifier,
     description: ..., note: ...}
known_limitations: [...]
```

只有 `availability: available` 的列会进入契约。`data/sealed/` 只能由 `budgetlab/evaluation/` 读取。

## 5. `results/` 对照结果格式（C 产出，D 读取）

```text
results/<matrix_id>/
├── matrix.json        # 预登记：tasks, systems, repeats, config 路径和哈希, code_version, 开始/结束时间
├── aggregate.csv      # 每个 run 一行（列见下）
├── aggregate.json     # 同一份数据的 JSON 版本
└── runs/<run_id>/     # 只复制这三个文件：summary.json, final_evaluation.json, report.md
```

`aggregate.csv` 的列，顺序固定，只能在末尾追加：

```text
matrix_id, task_id, system, proposal_source, repeat, run_id, code_version,
baseline_score, exploration_best_score, confirmation_status, delivered_experiment_id,
delivered_dev_score, holdout_score, dev_minus_holdout,
llm_calls, llm_requests, llm_tokens, llm_unknown_tokens, cost_usd,
wall_seconds, train_seconds, experiments, fits, rounds,
duplicates_blocked, invalid_rejected, direction_changes_agent, direction_changes_rule,
stop_reason
```

- `matrix_id` 的命名：开发期用 `dev-<日期时间>`，正式矩阵用 `final-<日期时间>`。D 的页面默认展示最新的 `final-*`，没有时展示最新的 `dev-*`，并明确标注"开发数据"。
- 曲线数据（最优分对累计 Token 和时间）直接取各 run 的 `summary.json` 中的 `trajectory`。

## 6. 经验库（P1，B 提供，A 使用）

```text
memory/<snapshot_id>.json     # 冻结后只读；run_config 中记录所用快照的哈希
[{lesson_id, version, conditions{rows?, positive_rate?, has_sentinel?, ...},
  action{kind, detail}, observed_effect{metric, delta, comparator, run_id, experiment_ids},
  support, counterexamples, status: candidate|supported_in_sources|deprecated, limitations}]
```

- B 提供 `match_lessons(profile, card, snapshot) -> list[dict]`，最多返回 3 条，由控制器放进上下文的 `lessons` 键。
- A 只负责在提示词里说明这些经验怎么用；A 不写经验库。
- 正式评测期间不更新快照。

## 7. 配置文件分段

`configs/*.yaml` 的顶层键和负责人：

| 键 | 负责人 |
|---|---|
| `task_id`、`cv_folds`、`split_seed`、`calibration_split_seeds`、`confirmation_split_seeds`、`training_seed`、`search_seed`、`min_effect_floor`、`primary_metric`、`text_columns`、`allowed_model_families`、`random_search_experiments` | C |
| `budget`、`loop` | B |
| `proposer`、`llm` | A |

- 开发期的实验配置各自新建文件，例如 `configs/llm-dev.yaml`、`configs/benchmark/dev.yaml`。
- 正式矩阵使用的配置在冻结时由协调人确认，之后不再改。

## 8. 对话式研究页的对接（A / C / D）

流程见 TEAM.md 第 4 节。本节只定义各角色之间传递的数据，具体实现由各负责人自定。

### 8.1 协议草稿 `DraftProtocol`（A 产出，D 展示，人确认后交给 C）

```python
class FieldDecision(BaseModel):     # 定义在 budgetlab/agents/protocol_agent.py
    name: str
    availability: Literal["available", "post_outcome", "identifier"]
    reason: str                      # 一句话说明理由，展示给人看

class DraftProtocol(BaseModel):
    title: str
    business_question: str
    prediction_time: str             # 例如 "before the outbound call is placed"
    target_column: str
    positive_label: str
    primary_metric: Literal["f1_macro", "accuracy", "roc_auc"]
    fields: list[FieldDecision]      # 必须覆盖除目标列以外的每一列
    questions_for_user: list[str]    # 拿不准、需要人确认的地方
```

- 输入：一句话描述、列名、开发数据画像（`profile_development` 的输出，**不带可用性标注**）。不能把 holdout 传给它。
- 调用协议 Agent 时也要计量 Token，记录到 `ui_state/llm_calls.jsonl`，和研究预算分开。
- 人确认（可以先修改）后，D 把最终结果转换成场景卡 dict（格式见第 4 节），交给 C 的 `register_csv_task`。草稿和最终版都保存在 `data/uploads/<task_id>/` 下：`draft_protocol.json`、`card.yaml`。
- **兜底路径（没有 LLM）**：示例任务的 `DraftProtocol` 由 D 直接从已有场景卡转换而来，`questions_for_user` 为空，并标注 `source=card`；新上传的 CSV 生成一份所有字段都待人确认的空白草稿，标注 `source=manual`。正常由 Agent 生成的草稿标注 `source=llm`。因此 `DraftProtocol` 需要增加字段 `source: Literal["llm", "card", "manual"]`。

### 8.2 通用 CSV 任务（C 提供，D 调用）

```python
# budgetlab/tasks/csv_task.py
register_csv_task(csv_path: Path, card: dict, data_root: Path) -> str   # 返回 task_id，例如 "upload-<8位哈希>"
validate_csv_for_task(csv_path: Path, target_column: str) -> list[str]  # 返回拒绝理由，空列表表示可以
```

- 注册的结果要**落到文件**，写到 `data/uploads/<task_id>/`（数据副本、`card.yaml`、`task.json`）。这样 `get_task(task_id)` 在训练子进程里也能找到它，C 负责让 `get_task` 能从这个目录发现上传的任务。
- 注册后照常用 `prepare_task(task_id, data_root)` 切出密封 holdout，再交给 `run_research`。
- 拒绝的条件：目标列不是两个取值、行数超过 10 万、列数超过 200、某一类样本数少于折数，或者确认后没有任何可用特征。

### 8.3 后台运行与进度（D 实现，读取第 1 节的 run 目录）

- 启动方式：子进程执行 `python -m budgetlab.cli research --config <生成的配置> --system <系统> --proposer <scripted|llm> --runs-root runs --data-root data`。页面生成的配置写到 `ui_state/configs/`，不要改 `configs/` 下的共享文件。
- 识别本次的 run 目录：启动前记下 `runs/` 里已有哪些目录，启动后新出现的那一个就是。进程信息写到 `ui_state/launches.jsonl`，页面刷新后可以重新接上。
- 步骤卡片只根据 `events.jsonl` 的 `event_type`、`rounds/round-NN.json` 和 `experiments/<id>.json` 渲染，不解析日志文本。对应关系如下：

| 卡片 | 事件或文件 |
|---|---|
| 协议与数据画像 | `protocol_accepted`、`profile_written` → `protocol.json`、`eda.json` |
| 基线与门槛标定 | `baseline_completed`、`calibration_completed`、`contract_frozen` → `calibration.json` |
| 第 N 轮提案 | `llm_call_*`（role=proposer）→ `rounds/round-NN.json` 中的 proposal、rejected、not_run |
| 训练与裁决 | `experiment_completed` / `experiment_failed`、`evaluation_recorded` → `experiments/<id>.json` |
| 规则动作 | `tool_search_started/completed`、`direction_changed`、`llm_call_*`（role=critic） |
| 停止与确认 | `stop_decided`、`confirmation_completed` → `confirmation.json`、`confirmation/split-*.json` |
| 交付与评测 | `delivery_frozen`、`run_terminal` → `summary.json`；`final_evaluation_recorded` |

- 进程退出后如果没有出现 `run_terminal` 事件，页面要显示"失败"，并展示 `logs/` 和子进程输出的最后几行。

### 8.4 证据工具与问答（D 提供工具，A 实现 Agent）

```python
# budgetlab/qa/evidence.py （D）— 只读，路径白名单：runs/ 和 results/；拒绝 data/sealed/、data/uploads/、.env
list_runs() -> list[dict]                        # run_id, system, task_id, 是否结束, 开始时间
get_summary(run_id) -> dict
get_experiment(run_id, experiment_id) -> dict
get_round(run_id, round_index) -> dict
get_llm_calls(run_id) -> list[dict]
get_final_evaluation(run_id) -> dict | None

# budgetlab/qa/faq.py （D）— 0 Token
QUICK_QUESTIONS: list[str]
answer_quick(question_id, run_id) -> QAAnswer

# budgetlab/qa/agent.py （A）
answer_open(question: str, run_id: str, history: list[dict]) -> tuple[QAAnswer, CallOutcome]
```

```python
class EvidenceRef(BaseModel):
    run_id: str
    kind: Literal["summary", "experiment", "round", "llm_call", "final_evaluation"]
    ref_id: str                        # 实验 id、轮次编号等

class QAAnswer(BaseModel):            # 定义在 budgetlab/qa/__init__.py，A 和 D 共用
    answer: str
    evidence: list[EvidenceRef]
    numbers: list[str]                 # 回答里出现的数字
    verified_numbers: list[str] = []   # 由程序填写：能在证据里找到的数字
    source: Literal["quick", "llm"]
```

- 程序负责核对：引用的证据必须存在；`numbers` 里的数字要能在本次工具返回的内容里找到（允许 4 位小数以内的舍入），找到的放进 `verified_numbers`，页面上找不到的标 ⚠️。
- 问答的 Token 记到 `ui_state/qa_calls.jsonl`，每个会话设上限（默认 20 次请求、50k Token）。
- 问答 Agent 只能调用上面这些只读工具，不能开跑、评测或修改任何文件。

