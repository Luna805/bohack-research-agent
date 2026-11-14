# 任务驱动的 Token 管理

## 功能概览

BudgetLab 按工作类型和研究进展选择模型，并在调用前预估资源、调用后记录实际用量。配置本地 DeepSeek 后，常规提案、Critic、协议草拟和开放问答可以使用本地端点；研究停滞或提案出现多条问题时，Proposer 才考虑强模型。模型只负责提案或文字回答，指标、裁决、晋级和停止仍由程序决定。

本功能需要显式启用。未启用时保持原有单模型方式；`scripted` 和 `random_search` 不会因配置路由而产生 LLM 请求。

## 路由规则

| 任务 | 默认档位 | 改变条件 |
|---|---|---|
| 研究 Proposer | `local` | 连续达到 `stagnation_threshold` 轮无改善，或最近反馈中至少有 `invalid_threshold` 条包含 `invalid`、`duplicate`、`rejected` 的问题时考虑 `strong` |
| 研究 Critic | `local` | 不自动升级 |
| 上传 CSV 后起草协议 | `local` | 可用 `task_tiers.protocol` 静态指定 `strong` |
| 开放问答 | `local` | 可用 `task_tiers.qa` 静态指定 `strong` |

考虑强模型后，程序先检查其**本次调用的预估** Token、请求数和已配置的美元成本是否容得下剩余预算。强模型未配置、缺少密钥或预估超预算时改用本地模型，并记录原因。本地模型也超预算时，原有控制器停止或拒绝调用。一次请求失败后不会在同一请求里自动改发给另一模型；下一轮会重新选择。

`invalid_threshold` 统计的是最近一次控制器反馈中的问题条数，可能来自同一轮的两个候选，不是跨所有轮次的累计数。路由只读取开发阶段的进展与反馈，不读取密封 holdout。

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
