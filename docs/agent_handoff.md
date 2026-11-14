# A · Agent 与模型 — 交付文档

> 角色：A（Agent 与模型）· 负责人：chier1 · 更新：2026-11-14 12:30（北京时间）
> 本文是 A 角色的交付说明。分工与文件归属见 `docs/TEAM.md`；模块接口见 `docs/INTERFACES.md`；进度表见 `docs/HANDOFF.md`（协调人维护）。

## 1. 交付总览

| # | 交付物 | 路径 | 状态 |
|---|---|---|---|
| 1 | 协议理解 Agent | `budgetlab/agents/protocol_agent.py` | ✅ 已交付，离线测试通过 |
| 2 | 真实 LLM 开发配置（含关闭思考） | `configs/llm-dev.yaml` | ✅ |
| 3 | `LLMSettings.extra_body` 支持 | `budgetlab/proposers.py` | ✅ |
| 4 | 测试（协议 Agent + extra_body 转发） | `tests/test_agent_protocol.py`、`tests/test_llm_http.py` | ✅ |
| 5 | 真实接口门禁 `probe-llm` | — | ✅ 通过（tool 模式） |
| 6 | 真实 LLM 的 Bank run | — | ✅ 3 次跑完（关闭思考后 2 次干净稳定） |
| 7 | 问答 Agent | `budgetlab/qa/agent.py` | ⏳ 未开始：等 D 的证据工具 |

## 2. 真实接口门禁（`probe-llm`）

- 模型：`qwen3.7-plus`，Base URL：阿里云 MaaS `compatible-mode` 端点，OpenAI 兼容。
- 结果：tool 模式**一次通过**，返回合法 `ProposalBatch`（2 个候选）；usage 取自原始 HTTP 响应（`requests_without_usage: 0`），失败请求按 unknown 记，不记 0。
- 凭证位置：`.env`（gitignore 保护）；`.env.example` 保持空模板。**不要**把 Key 写进 `.env.example`（它是 git 跟踪文件）。

## 3. 思考模式与 token 优化

`qwen3.7-plus` 是思考模型。默认（`max_output_tokens: 2000`）会把输出 token 打满并失败：

| | 输出 tokens | 耗时 | 结果 |
|---|---|---|---|
| 思考开启（首轮 probe） | 917 | 18.3s | 通过 |
| 思考开启（真实 run round 1） | 3532 | 60.9s | 2 次请求，round 2/3 `OutputTokenLimitExceeded` |
| **思考关闭（`extra_body: {enable_thinking: false}`）** | **329** | **8.9s** | 通过，单请求 |

修复：`LLMSettings` 增加 `extra_body` 字段，经 pydantic-ai 的 `model_settings["extra_body"]` 直通 OpenAI 请求；`configs/llm-dev.yaml` 设 `extra_body: {enable_thinking: false}`、`max_output_tokens: 3000`。这是 HANDOFF 待办 P1「`LLMSettings` 支持 `extra_body`」的落地。

## 4. 真实 LLM 的 Bank run（任务 2）

`python -m budgetlab.cli research --config configs/llm-dev.yaml --system budgetlab --proposer llm`

| run_id | 轮数 | 空轮 | invalid | 重复拦截 | 探索最优 | 确认 | LLM tokens | 用时 |
|---|---|---|---|---|---|---|---|---|
| `20261114T031257Z-budgetlab-2532ff` | 3 | **2** | 0 | 0 | 0.706 | confirmed_pass | 33.7k | 465s |
| `20261114T032702Z-budgetlab-cdfbe2` | 8（跑满） | 0 | 0 | 1 | 0.712 | confirmed_pass | 99.6k | 847s |
| `20261114T034204Z-budgetlab-142187` | — | — | — | — | — | — | — | 内存被杀 |
| `20261114T041641Z-budgetlab-6703b2` | 6 | 0 | 0 | 0 | 0.712 | confirmed_pass | 64.6k | 929s |

- 基线 `f1_macro=0.641`；scripted/random 的探索最优都是 0.710（见 HANDOFF）。
- `031257Z` 是关闭思考**之前**的 run：round 2/3 空轮（思考模型把输出 token 打满 → `OutputTokenLimitExceeded` → `no_valid_candidates`），正是它暴露了 bug，才有了 `extra_body` 关闭思考。
- `034204Z` 因系统内存不足被 Claude Code 回收（`status: killed`），无 `summary.json`，记为**未完成**。
- 关闭思考后两次 run（`032702Z`、`041641Z`）均 0 空轮 / 0 invalid / 探索最优 0.712 / `confirmed_pass`；`041641Z` 以 `diminishing_returns` 提前收敛，token 更低（64.6k vs 99.6k）。

**对比小结（一句话）**：
- 关闭思考是分水岭：`031257Z`（开）round 2/3 空轮；`032702Z` / `041641Z`（关）全程 0 空轮。
- 两次干净 run 探索最优**完全一致 0.712**（基线 0.641，+0.071），稳定。
- `041641Z` 更省：6 轮提前收敛（`diminishing_returns`），token 64.6k vs `032702Z` 的 99.6k。

**提案质量（任务 2 三项验收）**：
1. **引用证据**：每轮都引用 `tool-NN` / `rNN-cM` / `eda` / `critic_advice`，0 个无效引用（`invalid_rejected: 0`）。
2. **重复**：8 轮只 1 次被程序拦下（`duplicates_blocked: 1`）。
3. **语义信息**：正确识别 `pdays=999` 哨兵（"从未联系过"）、`unknown` 标签、经济指标冗余并 drop 掉；`intent` 有 explore/replan/pivot，critic 触发 2 次。

## 5. 协议理解 Agent（已交付）

接口符合 INTERFACES 8.1。对 D 的用法：

```python
from budgetlab.agents.protocol_agent import ProtocolAgent, build_protocol_context, score_draft
from budgetlab.proposers import LLMSettings

agent = ProtocolAgent(LLMSettings.from_config(config))
context = build_protocol_context(description, columns, profile)   # 自动剥离 availability
outcome = agent.draft(context)              # outcome.output 是 DraftProtocol；usage 记到 ui_state
score_draft(outcome.output, card)           # 对照任务说明算首次正确率
```

`DraftProtocol` / `FieldDecision` 为可变模型（人可在确认前编辑）；`source` 由程序盖章成 `llm`，LLM 无法自报。

**真实模型在 Bank 上的首次正确率与成本（任务 4）**：一句描述 + 无 availability 的开发集画像 → 首次生成即 **20/20 字段全对（首次正确率 1.0）**，正确把 `duration` 判成 `post_outcome`、`target=y`、`positive=yes`、`metric=f1_macro`；成本 **4861 tokens / 1 请求 / 15.6s**。它把拿不准的目标列名 `y` 放进了 `questions_for_user`（符合预期）。

## 6. 阻塞项

1. **问答 Agent 依赖 D**：`budgetlab/qa/agent.py` 要 `from budgetlab.qa import QAAnswer, EvidenceRef` 和 `from budgetlab.qa.evidence import ...`，但 `budgetlab/qa/` 目录 D 还没建。按文件归属 A 只能写 `agent.py`，需等 D 先落 `__init__.py`、`evidence.py`、`faq.py`。
2. **输入上下文偏大**：proposer 平均 ~10k input tokens/次。当前已够用，是否精简 `data_profile` 换更短上下文，留到有真实 A/B 对比再定。

## 7. 验证记录

- `probe-llm`：tool 模式通过（见第 2 节）；native/prompted 未测（tool 已可用）。
- `pytest -q tests/test_llm_http.py tests/test_agent_protocol.py` → 9 passed。
- `ruff check .` 与 `ruff format --check budgetlab tests` 通过。
- 全量 `pytest -q` → **37 passed**（237s）。
- 真实 LLM run 数字均来自 `summary.json`，未手填任何指标。

## 8. 下一步

1. Bank 稳定性已确认（关闭思考后 2 次干净 run，探索最优均 0.712）。可把结果同步给 B（提案接口）和 C（真实 LLM run 可用）。
2. D 落 `qa/` 后实现 `budgetlab/qa/agent.py`（`answer_open`）。
3. 如需更短上下文，做 `data_profile` 精简 A/B 并附 token 对比。

## 9. A 任务清单核对（对照 TEAM.md §3）

| # | 任务 | 状态 |
|---|---|---|
| 1 | 真实接口门禁 `probe-llm`（tool→native→prompted；思考模型补 `extra_body` 关思考） | ✅ tool 一次通过；`extra_body` 已落地 |
| 2 | Bank 跑 2–3 次 `--proposer llm` 看提案质量 | ✅ 3 次跑完（关闭思考后 2 次干净，0 空轮/0 invalid） |
| 3 | 调 `build_context`/提示词，附前后 token 对比 | ⚠️ 部分：思考关闭对比 917→329（输出 tokens）已完成；`build_context`/`data_profile` 精简**未做**（约 10k input/次已够用，留到有 A/B 再动） |
| 4 | 协议理解 Agent + Bank 打分记录首次正确率/成本 | ✅ 首次正确率 20/20=1.0，成本 4861 tokens |
| 5 | 问答 Agent `budgetlab/qa/agent.py` | ⏳ 阻塞：等 D 落 `qa/__init__.py`（`QAAnswer`）+ `evidence.py` |
| 6 | 无 API 时用 FunctionModel / 本地假服务器 | ✅ 已用（`test_agent_protocol.py` 用 FunctionModel、`test_llm_http.py` 用本地 FakeOpenAI） |

**结论**：除第 5 项（阻塞 D）和第 3 项的后半段（build_context 精简，非阻塞、当前够用）外，A 的其余任务均已交付并验证。
