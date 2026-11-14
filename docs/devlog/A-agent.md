# 开发日志 · A · Agent 与模型

新的写在最上面。每条包含：时间、谁（人或代理）、做了什么、怎么验证的（命令或 run_id）、遇到的问题、下一步。

### 2026-11-14 冻结后（约 20:30）· Yolo(A) + Claude Code，分支 `a/multitask`
- 做了：实现多分类与回归任务支持（在**新分支 `a/multitask`** 上，未碰冻结的 main / `benchmark-freeze` 矩阵）。核心是把「二分类专用」的四处——指标方向、效应量、模型族、目标编码——泛化成三种 `task_type`：`binary` / `multiclass` / `regression`。改动清单见下方表格。
- 验证：
  - `pytest`：新增 `tests/test_multitask.py` 8 个离线测试全过；`test_evaluator.py` 13 个全过（修正了一个旧测试：把「分数必须 0–1」改成**按指标**判定——回归的 RMSE 无上界、R² 可为负，分类指标仍强制 0–1）。
  - `ruff check .` 与 `ruff format --check` 全过。
  - 端到端（脚本化提案，离线 sklearn 数据，不联网）：`diabetes`（回归，R²）research 跑通 → holdout R²=0.571（CI [0.449, 0.654]）；`iris`（多分类，macro-F1）→ holdout F1=1.0。二分类主路径（Bank/Adult）由全量测试覆盖，未被破坏。
- 问题（务必读）：
  1. **这是跨角色改动**，动了 B 的 `schemas/pipeline/evaluator/search/contracts/state/worker/controller/data/profile/memory` 和 C 的 `evaluation/tasks`。按 `TEAM.md` 第 2 节，**合并前需在群里知会 B、C 并 review**；未 review 前不往 main 合。
  2. 分支是冻结安全的：正式矩阵的 `main` 一行没动，多任务只是加分项、不在正式成绩里。
  3. **效应量归一化只做了第一版**：回归用 R²（maximize，天然近似有界）为主指标；`min_effect`/`noise_floor` 仍按 `stdev` 计算，对 R² 合理，对 RMSE/MAE（minimize、有量纲）只在同一数据尺度下成立。跨任务不可比，见 handoff 的「已知限制」。
  4. CSV 上传（`csv_task.py`）**仍是二分类**；多分类/回归走内置任务卡（`iris` / `diabetes`）。
- 下一步：请 B/C review 后决定是否合入 main；回归的「尺度无关效应量」（相对基线改进比例）留到提交后。

## 多任务支持改动说明（分支 `a/multitask`）

| 文件 | 归属 | 改了什么 |
|---|---|---|
| `schemas.py` | B | `Metric` 加 `r2/rmse/mae`；`ModelFamily` 加 `ridge/random_forest_regressor/hist_gradient_boosting_regressor` 及对应 Spec；`TaskType`/`Direction` 别名 + `metric_direction()`；`task_type` 放开 `binary`→三值；放宽 `min_effect/noise_floor/min_effect_floor` 的 `le=1` 上界 |
| `pipeline.py` | B | logistic `solver="liblinear"`→`lbfgs`（支持多分类）；新增三个回归器分支；`score_predictions` 支持多分类 F1/accuracy/roc_auc(ovr) 与回归 R²/RMSE/MAE |
| `evaluator.py` | B | `result_problem` 按指标判定分数范围（回归只查有限性）；`evaluate_candidate`/`evaluate_confirmation` 加 `direction`（minimize 时 `delta<=-min_effect` 才 pass） |
| `data.py` / `worker.py` | B | 新增 `cv_splitter`（回归用 `KFold`，其余 `StratifiedKFold`）；`prepare_task` 回归不做分层切分；`load_development` 回归保留 float 目标；`DatasetBundle` 带 `task_type` |
| `state.py` | B | `ResearchState.optimize` + `add()` 按方向选「best」（minimize 取更小分） |
| `contracts.py` | B | `freeze_contract` 冻结 `task_type` 与 `decision_policy.direction=metric_direction(primary_metric)` |
| `search.py` | B | `baseline_spec(task_type)`（回归用 Ridge）；`SpecSampler._model` 覆盖三个回归器族 |
| `controller.py` | B | 全程透传 `task_type`；`evaluate_candidate`/`evaluate_confirmation` 传 `direction`；`finalize` 排序按方向 |
| `profile.py` | B | `profile_development` 按 task_type：二分类给 `positive_rate`，回归给 `target_mean/target_std`，多分类给 `n_classes/class_share` |
| `memory/match.py`、`memory/extract.py` | B | 非二分类缺 `positive_rate` 时回退 0.5，避免开记忆时 KeyError（经验库本身仍是分类专用） |
| `evaluation/__init__.py` | C | `metric_value`/`_resample_values` 泛化到多分类与回归；holdout 读入与预测输出按 task_type |
| `tasks/__init__.py` + `cards/iris.yaml`、`cards/diabetes.yaml` | C | `TaskDefinition` 加 `task_type`；新增两个离线内置任务 |
| `proposers.py` | A | `build_context` 加 `task_type/direction/target_mean`；`ScriptedProposer._moves` 覆盖回归器族（`_family_default`+`_TWEAKS`，class_weight 只对分类器） |
| `agents/protocol_agent.py` | A | `DraftProtocol.primary_metric` 扩到回归/多分类指标 + 提示词一句 |
| `configs/iris.yaml`、`configs/diabetes.yaml`（新） | — | 两个 demo 配置（diabetes 指定回归器族 + `r2`） |
| `tests/test_multitask.py`（新） | A | 8 个离线测试 |

## 代码改动说明（2026-11-14 · chier1 + Claude Code）

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `budgetlab/proposers.py` | `LLMSettings` 加 `extra_body: dict \| None = None`（L337）；`from_config` 读 `llm.extra_body`（L353）；`_agent` 里 `model_settings["extra_body"] = ...`（L403–405） | `qwen3.7-plus` 是思考模型，默认把输出 token 打满，round 2/3 报 `OutputTokenLimitExceeded`。`extra_body` 让 pydantic-ai 把 `enable_thinking: false` 原样直通 OpenAI 请求体，关掉思考省 token。属于 pydantic-ai 的 `model_settings` 透传，归 A 的 LLM 层管。 |
| `configs/llm-dev.yaml`（新） | A 的 LLM 开发配置：`proposer: llm`、正预算（`max_llm_tokens: 200000`/`max_llm_requests: 60`）、`extra_body: {enable_thinking: false}`、`max_output_tokens: 3000` | 真实 LLM 请求必须有正预算才授权（规范第 3、7 条）；关思考避免 token 膨胀，max_output_tokens 提到 3000 给关闭思考后的输出留足余量。 |
| `budgetlab/agents/protocol_agent.py`（新） | `FieldDecision` / `DraftProtocol`（含 `source` 字段）、`build_protocol_context`、`score_draft`、`ProtocolAgent` | 任务 4：把「用户一句话 + 数据列 + 画像」转成可编辑的 `DraftProtocol`，并对照任务说明算首次正确率。复用 `proposers._PydanticAIRole` 的计量（走同一 httpx 客户端、usage 取原始响应、失败记 unknown）。 |
| `budgetlab/agents/__init__.py`（新） | 只做导出 | 让 D 能 `from budgetlab.agents.protocol_agent import ...` 直接用。 |
| `tests/test_agent_protocol.py`（新） | 3 个离线测试 | 覆盖：`build_protocol_context` 剥离 availability、`score_draft` 对照 Bank 卡纠错、`ProtocolAgent` 用 `FunctionModel` 离线计量（不联网、不依赖 Key）。 |
| `tests/test_llm_http.py` | 加 `test_extra_body_is_forwarded_to_provider` | 确认 `extra_body` 真的进了 provider 请求体，而不是只存在配置里。 |


<!-- 示例
### 2026-11-14 13:00 · 姓名 + 代理
- 做了：…（提交 abc1234）
- 验证：pytest 通过；run 20261114T…
- 问题：…
- 下一步：…
-->
### 2026-11-14 约 16:45–17:00 · yirran（协调人）+ Claude Code，分支 `c/pre-freeze-fixes`（代 A 写问答 Agent，协调人要求）
- 做了：新建 `budgetlab/qa/agent.py`：`answer_open(question, run_id, history, *, store, settings, model=None) -> (QAAnswer, CallOutcome)`。程序先通过 D 的只读 `EvidenceStore` 收集证据（summary、实验行、每个实验后的最优分、各轮提案、LLM 调用记录、已评测时的 holdout），压成一个上下文，只发 1 次请求（复用 `_PydanticAIRole` 的计量，输出上限 1200）。模型只返回回答和引用；程序删掉不存在的引用（例如编造的实验 id、没评测时引用 holdout），并从回答里抽出数字逐个在证据里核对，填 `verified_numbers`。`QAAnswer`、`EvidenceRef` 按 INTERFACES 8.4 定义在 `budgetlab/qa/__init__.py`。
- 验证：`tests/test_qa_agent.py` 4 个离线测试（FunctionModel，不联网）：数字核对、假引用被删、没评测时不能引用 holdout、模型出错时如实报错。
- 下一步：现场用真实模型问几个问题，看回答长度和 Token（预计每问 6–10k 输入 Token）。

### 2026-11-14 约 12:10–12:30 · chier1 + Claude Code
- 做了：补跑第 3 次 Bank run（上次 `034204Z` 因内存不足被 Claude Code 回收 `status: killed`，无 summary）；这次单独重跑，不并发其它重活。
- 验证：`20261114T041641Z-budgetlab-6703b2` → 6 轮 0 空轮、0 invalid、0 重复拦截、探索最优 0.712（基线 0.641）、`confirmed_pass`、`diminishing_returns` 提前收敛，64.6k tokens / 929s。
- 问题：本机空闲内存仅 ~1.9 GB / 16 GB，是上次被杀的根因；重跑时未并发 pytest。
- 下一步：Bank 稳定性已确认（关闭思考后 `032702Z`/`041641Z` 两次干净 run，探索最优均 0.712）；等 D 落 `qa/` 后写问答 Agent。
  
### 2026-11-14 约 11:10–11:40 · chier1 + Claude Code
- 做了：
  ① `probe-llm` tool 模式跑通（模型 `qwen3.7-plus`，usage 取自原始 HTTP 响应）。
  ② 定位首轮失败：`max_output_tokens: 2000` 对思考模型太小，round 2/3 报 `OutputTokenLimitExceeded` → 空轮 → `no_valid_candidates`；给 `LLMSettings` 加 `extra_body` 字段，`configs/llm-dev.yaml` 设 `extra_body: {enable_thinking: false}` + `max_output_tokens: 3000`，关闭思考。
  ③ 新增 `test_extra_body_is_forwarded_to_provider`。
- 验证：probe 输出 tokens 917→329、耗时 18.3s→8.9s；`pytest tests/test_llm_http.py tests/test_agent_protocol.py` → 9 passed。真实 run `20261114T032702Z-budgetlab-cdfbe2`：8 轮跑满、0 空轮、0 invalid、`confirmed_pass`，探索最优 0.712（基线 0.641），LLM 99.6k tokens / 847s。（第 3 次补跑见上一节。）
- 提案质量（任务 2 三项验收）：① 证据引用——每轮都引用 `tool-NN`/`rNN-cM`/`eda`/`critic_advice`，0 个无效引用；② 重复——8 轮只 1 次被拦（`duplicates_blocked: 1`）；③ 语义信息——正确识别 `pdays=999` 哨兵（"从未联系过"）、`unknown` 标签、经济指标冗余（drop 掉），intent 有 explore/replan/pivot，critic 触发 2 次。
- 协议 Agent 实测（任务 4）：真实模型在 Bank 上一句描述 + 无 availability 画像 → 首次生成 20/20 字段全对（正确率 1.0），正确排除 `duration`（post_outcome）；成本 4861 tokens / 1 请求 / 15.6s；拿不准的 `y` 列名放进了 `questions_for_user`。
- 问题：输入上下文仍偏大（proposer 平均 ~10k input tokens/次），但已够用；要不要精简 `data_profile` 换更短上下文，等有真实 A/B 对比再动。
- 下一步：Bank 稳定性已确认（关闭思考后 `032702Z`/`041641Z` 两次干净 run，探索最优均 0.712）；等 D 落 `qa/__init__.py`+`evidence.py` 后写问答 Agent；P1「extra_body + 关闭思考」已完成。

### 2026-11-14 约 11:55–11:06 · chier1 + Claude Code
- 做了：A 角色开工。
  ① 新建 `budgetlab/agents/protocol_agent.py`：`FieldDecision` / `DraftProtocol`（含 `source` 字段）、`build_protocol_context`（剥离 availability）、`score_draft`（对照任务说明算首次正确率）、`ProtocolAgent`（复用 `proposers._PydanticAIRole` 的计量与单 httpx 客户端；`source` 由程序盖成 `llm`）；`budgetlab/agents/__init__.py` 只做导出。
  ② 新建 `configs/llm-dev.yaml`：`proposer: llm`，`max_llm_tokens: 200000`、`max_llm_requests: 60` 正预算，模型/Base URL/Key 一律走 `.env` 环境变量。新增 `tests/test_agent_protocol.py`（3 个离线测试）。
  ③ 填写`.env`， `LLM_MODEL`/`LLM_BASE_URL`/`LLM_API_KEY` 三个环境变量，跑真实接口门禁 `python -m budgetlab.cli probe-llm --config configs/llm-dev.yaml`（tool 模式）。
- 验证：`probe-llm` 正常读到模型 `qwen3.7-plus` 和 MaaS Base URL，请求到达网关；返回 401 `API-key is blocked` / `invalid_api_key`（usage 记录为 unknown，符合"失败请求记 unknown"的规则）。
- 问题：**API Key 被服务端拒绝**，不是代码问题。需用户核对 Key 是否有效/过期/被 block，以及 `qwen3.7-plus` 的权限。
- 下一步：Key 确认后按 tool→native→prompted 重跑门禁，再跑 2–3 次 Bank 真实 run。
