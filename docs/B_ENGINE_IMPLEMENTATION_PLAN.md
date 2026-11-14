# B · 研究引擎 P0/P1 实施计划

> 用途：本文件可以直接交给实现 Agent。  
> 角色：B · 研究引擎。  
> 顺序：必须先完成 P0；P0 未验收前不得进入 P1。  
> 原则：现有主循环已经基本完成，本任务以补测试、修可靠性问题、冻结接口为主，不得重写引擎。

## 0. Agent 开工要求

开始修改前依次阅读：

1. `AGENTS.md`
2. `docs/TEAM.md`
3. `docs/INTERFACES.md`
4. `docs/HANDOFF.md`
5. `budgetlab/controller.py`
6. `budgetlab/state.py`
7. `budgetlab/budget.py`
8. `budgetlab/evaluator.py`
9. `budgetlab/runner.py`
10. `tests/test_controller_integration.py`
11. `tests/test_budget_ledger.py`
12. `tests/test_evaluator.py`

执行约束：

- 只修改 B 负责的引擎文件、对应测试、`budgetlab/memory/` 和 `docs/devlog/B-engine.md`。
- 不修改 A 的 `budgetlab/proposers.py`、C 的任务和评测文件、D 的 reporting/UI 文件。
- 需要其他角色配合时，只输出接口需求，不越权修改。
- 不读取、打印或提交 `.env`、API Key 和 `data/sealed/` 内容。
- 不发送真实 LLM 请求，除非用户明确授权且 LLM 预算为正数。
- 不处理工作区内与本任务无关的未跟踪文件。
- 不提交、不推送，除非用户明确要求。
- 修改必须最小化；不得删除测试或放宽断言来制造通过结果。

建议分支：

```text
b/engine-stability   # P0
b/memory             # P1
```

## 1. 当前已完成能力

以下能力已经存在，不应重新实现：

- `run_research()` 支持 `random_search`、`budgetlab_no_schedule`、`budgetlab`。
- 研究阶段只使用 development 数据，holdout 由独立评测读取。
- 场景卡控制字段可用性。
- 基线、噪声标定、`min_effect` 和契约冻结已实现。
- Proposer 每轮返回两个候选，程序负责筛查、训练和裁决。
- 实验在独立子进程中运行，支持超时和日志。
- 候选使用相同折进行配对比较。
- Token、请求、实验、fit、时间统一经过预算预留和结算。
- 工具搜索、停滞、replan、Critic 和停止规则已实现。
- 最优候选使用三个新切分进行 confirmation。
- confirmation 未通过时交付基线。
- summary、events、rounds、experiments、delivery、replay、reproduce 已实现。

---

# P0 · 主循环稳定与冻结

## P0-1 建立基线

执行：

```bash
uv sync --frozen --extra dev --extra llm --extra ui
python -m pytest -q
ruff check .
ruff format --check budgetlab tests
```

记录 Git commit、dirty 状态、测试数量、失败信息和环境问题。基线失败时先确认是否为已有问题，不得盲目修改生产代码。

## P0-2 接口产物测试

新建 `tests/test_engine_interfaces.py`，至少覆盖：

1. `run_research()` 返回 `summary_version == 1`。
2. 返回值和磁盘上的 `summary.json` 一致。
3. run 目录存在以下必要文件：
   - `summary.json`
   - `report.md`
   - `events.jsonl`
   - `run_config.json`
   - `protocol.json`
   - `contract.json`
   - `calibration.json`
   - `budget.json`
   - `delivery/frozen_delivery.json`
   - `delivery/model.joblib`
4. `events.jsonl` 的 `seq` 从 1 连续递增。
5. 成功 run 最终包含 `run_terminal`。
6. `replay_run()` 不启动训练、LLM，也不修改预算文件。
7. `reproduce_run()` 的 dataset hash 和 spec hash 与冻结交付一致。
8. summary 中 system、proposal source、stop reason、budget 字段完整。

测试必须使用临时目录和 smoke fixture，不联网、不依赖 API Key。

## P0-3 主循环行为测试

新建 `tests/test_engine_loop.py`。优先在测试文件内定义零 Token Fake Proposer 和 Fake Critic，不修改生产接口。

至少覆盖：

1. 两个候选便宜且预算充足时都运行。
2. 候选较慢或预算不足时只运行排序第一的候选。
3. 同一批两个规格相同的候选被拒绝。
4. 与历史实验重复的候选被拒绝，`duplicates_blocked` 增加。
5. comparator 不存在时拒绝。
6. 证据引用不存在时拒绝。
7. 未批准字段和非法特征动作被拒绝。
8. 连续空提案触发 `no_valid_candidates`。
9. 连续无有效提升后触发工具搜索。
10. 达到 `stagnation_replan` 后上下文进入 `replan`。
11. Critic 在同一停滞周期内最多调用一次。
12. 有效提升会重置停滞、工具搜索和 Critic 状态。
13. 达到 `stagnation_stop` 后产生 `diminishing_returns`。
14. 达到最大轮数后产生 `max_rounds`。
15. LLM 预算不足时不调用 Proposer，并产生 `llm_budget_exhausted`。
16. 训练预算不足时产生 `budget_exhausted`，且不越过预算。
17. confirmation 失败时交付基线。
18. confirmation 缺少有效切分时为 `inconclusive` 并交付基线。
19. confirmation 通过时才交付 finalist。

断言应检查真实产物和最终状态，不只检查 mock 调用次数。

## P0-4 收紧证据引用检查

当前 `screen_candidates()` 只要求 `evidence_refs` 中至少一个引用有效。改为所有引用都必须属于：

```text
已有 experiment id + eda + calibration + scenario_card
```

预期实现：

```python
if not set(candidate.hypothesis.evidence_refs).issubset(allowed_refs):
    reason = "one or more evidence_refs are unavailable"
```

测试四种情况：全部有效、部分无效、只引用 `eda/calibration`、comparator 不存在。不得修改 `Hypothesis` 或 `ProposalBatch` Schema。

## P0-5 加固 Runner 异常结算

检查 `Runner.execute()` 在 reserve 之后的所有退出路径，保证：

- 正常结束按实际 experiments、fits、seconds 结算。
- 超时或结果缺失时，无法确认的 fits 进入 unknown，不能记成 0。
- `subprocess.run` 抛出 `OSError` 时 reservation 被结束，并生成 failed result。
- worker 非零退出且没有结果文件时生成明确错误。
- result JSON 损坏时 reservation 被结束，并生成明确错误。
- 能写日志时始终写 stdout/stderr。
- 任何可恢复异常都不能留下永久 `reserved` 状态。

不要捕获并吞掉 `KeyboardInterrupt` 或 `SystemExit`。

新增测试模拟：`OSError`、无结果文件、损坏 JSON、超时。

## P0-6 验证尾部预算

当前尾部预算用于：

```text
3 个 confirmation seed × 候选/基线各一次 = 6 个实验
最终 refit = 1 个实验
```

新增测试验证：

1. exploration 不能使用尾部 7 个实验预算。
2. fit 预算保留 `6 × cv_folds + 1`。
3. exploration 接近上限时仍能完成 finalize。
4. finalize 开始后尾部 reserve 才释放。
5. 没有 finalist 时仍能完成基线 final refit。
6. `budget.json` 最终没有状态为 `reserved` 的记录。

## P0-7 失败终止证据

成功 run 使用 `run_terminal`。失败 run 应保留明确证据，建议新增 `run_failed` 事件：

- 不改变 `run_terminal` 的成功语义。
- 记录异常类型、失败阶段和清理后的预算摘要。
- 不记录密钥、完整环境变量或密封数据。
- 新增前通知 D，因为 UI 会读取事件流。
- 未完成协调前，不修改 D 的 UI 判断逻辑。

如果时间有限，优先保证 Runner 结算正确；事件新增可在协调后完成。

## P0-8 三系统回归

依次运行：

```bash
python -m budgetlab.cli research --config configs/bank_marketing.yaml --system random_search
python -m budgetlab.cli research --config configs/bank_marketing.yaml --system budgetlab_no_schedule --proposer scripted
python -m budgetlab.cli research --config configs/bank_marketing.yaml --system budgetlab --proposer scripted
```

每个 run 检查：

- 有明确 `stop_reason`。
- 没有未结算 reservation。
- experiments、fits、seconds 未超过预算。
- summary 与 experiment、confirmation、delivery 一致。
- `delivery/model.joblib` 存在且哈希匹配。
- `report.md` 数字与 summary 一致。
- random search 的 LLM calls、requests、tokens 均为 0。
- scripted proposer 的 LLM requests、tokens 均为 0。
- replay 不修改预算和研究产物。

开发回归允许 dirty；正式冻结结果必须来自非 dirty commit。

## P0-9 接口冻结

向其他角色确认：

| 使用方 | 确认内容 |
|---|---|
| A | `ResearchState` 是否提供提案上下文所需状态 |
| C | `run_research()`、summary 和 run 目录格式是否稳定 |
| D | events、rounds、experiments 和 summary 是否可渲染 |

禁止：

- 改已有参数名称和含义。
- 删除或重命名 summary 字段。
- 改已有 event type、裁决状态的语义。
- 未协调就做破坏性修改。

新字段只能追加。发现必须破坏接口时停止并报告用户。

## P0 验收标准

- 新增测试和原有测试全部通过。
- `ruff check .` 通过。
- `ruff format --check budgetlab tests` 通过。
- 三个系统都完成 Bank 回归。
- 无预算越界和未结算 reservation。
- confirmation 失败时确定回退基线。
- C、D 依赖的产物格式未破坏。
- `docs/devlog/B-engine.md` 记录验证命令和 run ID。

P0 完成后先汇报，不要自动开始 P1，除非用户已明确要求同时实施 P1。

---

# P1 · 经验库

## P1-1 模块结构

新增：

```text
budgetlab/memory/
├── __init__.py
├── models.py
├── store.py
├── extract.py
├── match.py
└── snapshots/
```

职责：

| 文件 | 职责 |
|---|---|
| `models.py` | Lesson 和 Snapshot 的严格模型 |
| `store.py` | 原子读写、规范化和快照哈希 |
| `extract.py` | 从完成 run 提取经验草稿 |
| `match.py` | 根据 profile 和场景卡匹配最多 3 条经验 |
| `__init__.py` | 导出稳定 API |

经验库内部模型不要放进共享 `schemas.py`，除非已确认需要跨角色共享。

## P1-2 Lesson 数据模型

每条 Lesson 至少包含：

```text
lesson_id
version
conditions
action
observed_effect
support
counterexamples
status
limitations
```

`status` 只能是：

```text
candidate
supported_in_sources
deprecated
```

`observed_effect` 至少包含：

```text
metric
delta
comparator
run_id
experiment_ids
```

模型应拒绝未知字段和缺失必填字段。

## P1-3 快照存储

实现并导出：

```python
load_snapshot(path: Path) -> list[dict]
write_snapshot(path: Path, lessons: list[dict]) -> str
snapshot_hash(lessons: list[dict]) -> str
```

要求：

- 使用 `atomic_write_json()`。
- 相同内容产生相同哈希。
- 输入顺序不造成无意义哈希变化。
- 损坏 JSON 和非法 Schema 明确失败。
- 冻结快照只读，不在原文件上增量修改。

## P1-4 经验提取

从程序证据提取：

```text
条件 → 动作 → 效果 → 证据
```

允许的事实来源：`eda.json`、`scenario_card.json`、`contract.json`、`experiments/*.json`、`confirmation.json`、`summary.json`、`events.jsonl`。

禁止：

- 把 LLM 或 Critic 文字直接当成事实经验。
- 使用 holdout 分数生成研究经验。
- 读取 `data/sealed/`。
- 为 failed、timeout、invalid 比较伪造 delta。

每个完成 run 写：

```text
runs/<run_id>/memory_draft.json
```

建议规则：

- exploration `candidate_pass`：`candidate`。
- 最终 `confirmed_pass`：可升级为 `supported_in_sources`。
- invalid：不生成正向经验。
- `not_met`：可作为 counterexample，不成为正向 Lesson。

## P1-5 匹配条件和 API

从开发集 profile 和场景卡提取稳定条件：数据量区间、正类比例、类别不平衡、字段类型数量、sentinel、高缺失、primary metric、可用模型族。

不得包含 holdout、密封数据统计、密钥或无证据业务推断。

实现：

```python
match_lessons(profile: dict, card: dict, snapshot: list[dict]) -> list[dict]
```

要求：

- 排除 `deprecated` 和条件不兼容经验。
- support 高的优先，counterexample 多的降权。
- 排序确定性。
- 最多返回 3 条。
- 空快照返回空列表。

## P1-6 接入主循环

在 `ResearchState` 追加：

```python
lessons: list[dict] = field(default_factory=list)
```

`setup_run()` 的接入顺序：

```text
生成 profile
→ 加载冻结快照
→ match_lessons
→ 计算快照哈希
→ 使用真实哈希冻结 contract
→ 创建包含 lessons 的 ResearchState
```

替换当前 `memory_snapshot_hash=stable_hash([])` 硬编码。禁用经验库时继续使用空快照哈希，行为必须与当前版本一致。

在 `run_config.json` 追加：

```json
{
  "memory": {
    "enabled": true,
    "snapshot_ref": "...",
    "snapshot_hash": "...",
    "matched_lesson_ids": ["..."]
  }
}
```

## P1-7 与 A 对接

`budgetlab/proposers.py` 归 A，B 不直接修改。向 A 提交接口需求：

```python
# build_context() 返回值追加
"lessons": state.lessons
```

传给 A 的 Lesson 只包含 `lesson_id`、`conditions`、`action`、`observed_effect`、`limitations`。经验只能影响提案，不能绕过候选验证、去重、预算和裁决。

## P1-8 正式评测只读

建议配置：

```yaml
memory:
  enabled: true
  snapshot: budgetlab/memory/snapshots/bank-v1.json
  update_after_run: false
```

新增配置段前先和协调人确认。正式矩阵期间：

- 所有 run 使用相同冻结快照。
- `update_after_run: false`。
- 前一个正式 run 不改变后一个 run。
- contract 和 run_config 记录快照哈希。
- 找不到配置快照时明确失败，不静默替换。

## P1-9 测试和对照

新建 `tests/test_engine_memory.py`，至少覆盖：

1. 快照写入并重新加载。
2. 相同内容得到相同哈希。
3. 非法 Lesson 和损坏 JSON 被拒绝。
4. deprecated 和不兼容 Lesson 不参与匹配。
5. 匹配最多 3 条且顺序确定。
6. 禁用经验库时主循环行为不变。
7. contract 记录正确 snapshot hash。
8. run_config 记录快照和匹配 Lesson ID。
9. memory draft 的 run/experiment 引用真实存在。
10. 正式只读模式不修改快照。

使用相同任务、配置、seed 和预算运行：

```text
对照组：memory.enabled=false
实验组：memory.enabled=true
```

比较重复提案、非法提案、达到提升的轮数、实验数、Token、最优开发分数和 confirmation 状态。没有真实 LLM 时只能证明经验进入上下文，不能声称提升效果。

## P1 验收标准

- 快照能够严格校验、原子读写和稳定哈希。
- run 能生成带证据的 `memory_draft.json`。
- 新 run 最多匹配 3 条经验。
- contract 和 run_config 记录真实快照哈希。
- 禁用经验库时行为不变。
- A 可通过 `ResearchState.lessons` 接入上下文。
- 正式矩阵期间经验库只读。
- 完成至少一次有经验/无经验功能对照。
- 全部测试和 lint 通过。
- `docs/devlog/B-engine.md` 已更新。

---

## 2. 最终验证

```bash
python -m pytest -q
ruff check .
ruff format --check budgetlab tests
```

P1 额外执行：

```bash
python -m pytest -q tests/test_engine_memory.py
```

任何影响主循环的修改都必须重新运行三个 Bank 系统，不能只跑单元测试。

## 3. Agent 最终汇报格式

```text
完成阶段：P0 / P1

修改文件：
- 路径：修改目的

实现结果：
- 已完成行为
- 未完成或主动放弃行为

验证：
- pytest 命令与结果
- ruff 命令与结果
- Bank 回归 run_id 与 stop_reason

接口影响：
- 新增字段或事件
- A、C、D 需要的配合

风险与下一步：
- 剩余风险
- 推荐后续工作
```

不得只回复“已完成”或只列出修改文件。
