# 任务驱动的 Token 管理

## 一句话讲清创新

**把 Token 当作研究资源分配，而不是把所有问题交给同一个模型。** BudgetLab 先判断当前任务需要多少推理能力、还有多少预算、上一轮提案是否有效，再决定调用本地模型还是更强的模型；调用前预留 Token，调用后把用量和后续实验结果记在同一条可追溯的研究链上。

这个想法针对企业部署的现实问题：公司已经有本地 DeepSeek，但研究 Agent 的任务难度不断变化。简单问答、协议草拟、常规实验提案没有必要默认消耗昂贵模型的 Token；遇到研究停滞时，也不能只因“本地优先”而失去尝试更强模型的机会。**升级必须有任务信号和预算依据，是否有效最终由训练结果裁决。**

## 创新机制：任务、反馈、预算三道决策

1. **按任务分配能力。** 研究提案、Critic、协议草拟和问答的目标不同，分别配置模型档位。程序能直接回答的指标与裁决问题仍由程序处理，不消耗提案 Token。
2. **按反馈决定何时升级。** Proposer 默认使用本地模型；只有研究连续没有改善，或最近一轮出现多条无效／重复候选，才考虑强模型。触发信号来自开发阶段的真实研究记录，不由 LLM 自评。
3. **先核预算，再发请求。** 在强模型调用前估算 Token、请求数及已配置的成本。预算容不下就继续用本地模型；已发请求却拿不到 usage，则记为未知消耗，不能算免费。
4. **用实验结果检验分配是否值得。** 模型输出只是一份假设，后续训练、成对比较与确认仍由程序完成。路由原因、模型和 Token 消耗可与实验效果对照，才有条件评估“更多 Token 是否换来更多有效研究”。

这是一套**可审计的确定性调度规则**，不是声称已经训练出最优模型路由器，也不是按隐私或敏感程度做模型分流。本功能需要显式启用；未启用时保持原有单模型方式。`scripted` 和 `random_search` 不会因配置路由而产生 LLM 请求。

## 答辩时怎么讲

**30 秒版本：**

> 企业已经部署本地 DeepSeek，直接把每一步都交给昂贵模型会浪费 Token，但永远只用本地模型又可能在难题上停滞。BudgetLab 把 Token 纳入研究预算：常规工作先用本地模型；当连续实验没有改善或提案质量下降时，程序检查剩余预算，再决定是否升级。每次选择都有原因、预留和实际用量，最终看实验结果，而不是让模型自己宣布“这次升级有用”。

**演示例子（说明机制，不是实测成绩）：** 第一轮由本地模型提出两个候选，程序运行并记录结果；若后续两轮没有改善，下一轮尝试强模型。假设强模型这次预估需要 8,000 Token，而剩余额度只有 5,000，系统会保留本地档位并记录 `strong_tier_budget_shortfall`。评委可以沿着日志看到“为什么选、花了多少、实验有没有进步”。这些数值仅用于解释流程，不是项目运行结果。

**可以展示的证据：** `run_config.json` 证明本次阈值和预算，`llm_calls.jsonl` 证明每次模型选择与实际用量，实验与裁决文件证明结果由程序计算。若没有本地端点，演示应明确标成假模型测试或机制说明，不把它说成真实 DeepSeek 对照。

## 路由规则

| 任务 | 默认档位 | 改变条件 |
|---|---|---|
| 研究 Proposer | `local` | 连续达到 `stagnation_threshold` 轮无改善，或最近反馈中至少有 `invalid_threshold` 条包含 `invalid`、`duplicate`、`rejected` 的问题时考虑 `strong` |
| 研究 Critic | `local` | 不自动升级 |
| 上传 CSV 后起草协议 | `local` | 可用 `task_tiers.protocol` 静态指定 `strong` |
| 开放问答 | `local` | 可用 `task_tiers.qa` 静态指定 `strong` |

考虑强模型后，程序先检查其**本次调用的预估** Token、请求数和已配置的美元成本是否容得下剩余预算。强模型未配置、缺少密钥或预估超预算时改用本地模型，并记录原因。本地模型也超预算时，原有控制器停止或拒绝调用。一次请求失败后不会在同一请求里自动改发给另一模型；下一轮会重新选择。

`invalid_threshold` 统计的是最近一次控制器反馈中的问题条数，可能来自同一轮的两个候选，不是跨所有轮次的累计数。路由只读取开发阶段的进展与反馈，不读取密封 holdout。

## 怎样证明它有价值

在同一任务、相同数据切分和实验预算下，预先登记三组策略：始终本地、始终强模型、任务驱动路由。比较交付方案的 holdout 指标、总 Token、真实用时、合法提案比例和每次有效改善消耗的资源。只有对照结果支持时，才能说路由在某个任务上“以更少资源保持接近的效果”或“在相同预算下提高效果”。

当前代码测试证明的是**选择逻辑、预算边界和日志可追溯**，并未证明本地 DeepSeek 的效果，也没有证明节省了多少 Token 或费用。没有公司端点时，答辩应把它呈现为已实现的调度机制与可复现的验证设计，不能展示虚构的节省百分比。

## 配置研究运行

在任务配置中保留原有预算字段，加入以下设置。`strong` 可省略，此时全部研究调用走本地模型。模型名应填写部署服务实际接受的名称。

```yaml
proposer: llm
budget:
  max_llm_tokens: 300000
  max_llm_requests: 60
  # 保留 max_experiments、max_fits 等原有字段
llm:
  output_mode: tool
  max_output_tokens: 3000
  output_retries: 1
token_management:
  enabled: true
  stagnation_threshold: 2
  invalid_threshold: 2
  local:
    model: your-local-deepseek-model
    base_url: http://localhost:8000/v1
    api_key_required: false
  strong:
    model: your-approved-strong-model
    base_url: https://your-approved-endpoint/v1
    api_key_env: STRONG_MODEL_API_KEY
```

`local` 和 `strong` 都需显式写 `model`、`base_url`。档位可覆盖公共 `llm` 的 `output_mode`、`max_output_tokens`、`output_retries`、`timeout_seconds`、`extra_body` 以及输入和输出的每百万 Token 单价。

- 本地服务**无需鉴权**时才设置 `api_key_required: false`。客户端会给 SDK 一个占位字符串；它不是密钥，也不表示调用不耗 Token。
- 需要鉴权时，用 `api_key_env` 指定密钥所在的环境变量；未指定时沿用 `LLM_API_KEY`。不要把密钥值写入 YAML 或提交到仓库。
- 只在提供输入和输出单价后，美元成本才有可用依据。未配置价格时仍统计 Token 和请求数；显示的零美元不能解释为实际运行成本为零，本地 GPU 时间也未折算成美元。
- 路由阈值随运行配置保存到 `run_config.json`。一次运行中途不要修改配置来解释已有结果。

## 配置对话页

在 `ui_state/token_management.yaml` 放置同样的路由设置，内容以 `token_management:` 为顶层键。页面会把它叠加到现有矩阵的 LLM 设置，并传给页面启动的研究运行。`ui_state/` 不入库；密钥仍只放在环境变量中。

```yaml
token_management:
  enabled: true
  local:
    model: your-local-deepseek-model
    base_url: http://localhost:8000/v1
    api_key_required: false
  # strong 可暂时省略
  task_tiers:
    protocol: local
    qa: local
```

页面会按所选任务的模型和密钥要求检查 LLM 是否可用；无鉴权本地端点不需要全局 `LLM_API_KEY`。如果将 `protocol` 或 `qa` 指向 `strong`，该档位必须配置完整。协议草拟与问答的实际模型和路由原因写入各自的 `ui_state` 调用日志。

开放问答仍受每个页面会话 **20 次请求、50,000 Token** 的上限约束。发送前按上下文和最大输出量保守估算；剩余额度不足时不发请求。协议草拟是单次调用，使用所选档位的输出上限，其用量与研究预算分别记录。

## 预算与审计

研究调用仍经过 `controller.metered_call`：先预留所选模型的预估 Token／请求，再按服务返回的 usage 结算。缺少 usage 的请求按保守估计记入 `unknown`，不能算作零消耗。`runs/<run_id>/llm_calls.jsonl` 中每条调用记录包括：

| 字段 | 含义 |
|---|---|
| `planned` | 调用前预留的资源 |
| `usage`、`unknown` | 实际已知与未知用量 |
| `details.model` | 实际调用的模型 |
| `details.route_tier` | `local` 或 `strong` |
| `details.route_reason` | 如 `routine_proposal`、`research_stagnation`、`strong_tier_budget_shortfall` |
| `error` | 调用失败原因；无错误时为 `null` |

调用仍对应原有 ledger 事件。路由记录用于解释模型选择，不参与实验指标或裁决计算。

## 启用前验证

1. 确认本地服务提供当前客户端可用的 OpenAI 兼容接口，记录其 `model`、`base_url` 和鉴权方式。
2. 在 LLM 预算为正且明确允许真实调用的环境中，用项目的 `probe-llm` 检查工具输出、两个候选的 Schema、usage 和超时行为。
3. 先运行小任务，核对调用记录中的模型、路由原因、`planned`、`usage` 和 `unknown`；之后对照本地固定、强模型固定、任务路由三种策略的效果与资源消耗。

目前已用假模型验证路由、预算预留和调用记录，并通过仓库测试；**尚未使用公司的本地 DeepSeek 端点做真实兼容性或成本节省实测**，因此不承诺具体节省比例。
