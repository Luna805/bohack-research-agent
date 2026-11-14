# BudgetLab：夜间无人值守实施清单

> 编制：2026-11-14，Asia/Shanghai（UTC+8）。
> 项目：`C:\AAAProjects\bohack\bohack-research-agent`。
> 依据：`BoHack2026_Research_Agent_最终方案_v3.md` 与 `BoHack2026_BudgetLab_详细实施方案_v3.0.md`。
> 当前交付是任务清单与提示词；尚未启动夜间开发、创建 Goal 或设置定时任务。
> 默认运行窗口：启动后最多 6 小时，最后 30 分钟用于验证与交接。完成即可提前结束，不需要凑满时长。

## 1. 睡醒后应当得到什么

**优先目标：一个能在本机运行、能训练真实分类器、能记录预算和证据、能通过核心测试的 BudgetLab 最小工程闭环。**

夜间先完成可自动验收的代码工作；API、Kaggle 账号或正式评测条件缺失时，不等待用户回答，也不冒充已验证成功。

| 验收层级 | 具体交付 | 准确称呼 |
|---|---|---|
| A：基础必做 | 可安装工程、严格 Schema、固定数据/切分、真实 Pipeline/Runner、随机搜索、标定/确认、预算/事件、冻结交付、离线两轮 Controller 测试、报告与复现 | 确定性研究引擎和离线控制流已验收 |
| B：条件达成 | 已有明确消费授权和可用配置时，真实 PydanticAI 接口通过最终 Schema 测试，并完成两轮真实 LLM 提案→真实训练→反馈 | 真实 LLM 闭环已验收 |
| C：有余量再做 | 在剩余时间内实现可解释双候选策略、Critic/工具调度规则测试、正式矩阵预登记和只读报告增强 | 仅声明实际完成、实际测过的能力 |

没有真实 API 验证时，A 层仍可以交付，但 B 层必须标为 `blocked_external`。不得把脚本化提案、fixture 或离线模拟说成真实 LLM 研究；也不得因此宣称 v3.0 整体 P0 全部完成。

**夜间不跑完整 24-run 正式矩阵，不展开经验迁移、自定义代码沙箱、复杂 UI、多模型、时间/分组切分。** 保留对应接口和配置即可，不写假实现占位后报告支持。

## 2. 睡前设置与启动方式

### 2.1 用户睡前检查

- [ ] 工作区是上述项目，启动时使用可执行代码/工具的模式，而不只是 Plan 模式。
- [ ] 电脑接通电源、网络可用、应用保持运行；在 Windows 电源设置中确认夜间不会自动休眠或因合盖进入睡眠。请用户自行确认，不让 Agent 擅自更改系统电源策略。
- [ ] 当前工具权限允许工作区写入和必要的依赖下载；不要求关闭所有保护，也不授权 Agent 绕过拒绝。
- [ ] 账户有可用的编码 Agent 配额；项目程序内部的 LLM 预算不包含编码 Agent 自身用量。
- [ ] 需要真实 API 测试时，已有模型配置、凭证和明确总预算；没有也可启动默认离线路线。
- [ ] Kaggle 未完成规则确认或凭证未配置时，选择白天处理；夜间不代替用户接受新协议。
- [ ] 将 `NIGHT_RUN_PROMPTS.md` 的“主启动提示词”发送给 Agent；需要真实 API 测试时再附加其中的预算授权段。

本地项目任务要保持计算机和桌面应用运行。官方设置文档的“Prevent sleep while running”目前明确介绍的是 macOS/Linux，不应假设本 Windows 环境一定提供同样开关。[R1][R2]

### 2.2 推荐启动机制

如果客户端支持 Goal，使用 `/goal` 或明确要求创建 Goal，令目标带有完成条件并跨轮推进；Goal 不扩大原有权限，也可能因配额、连接、审批或外部阻塞而停止。[R3]

本次是“睡前启动一次连续开发”，不需要另建周期定时任务。普通会话也能执行提示词，但一句“持续工作”不能保证工具会话中断后自动重启。用阶段状态和交接文件保证可恢复，不编写无人监管的无限自启动循环。

## 3. 执行预算与默认决策

| 项目 | 夜间默认值 | 处理规则 |
|---|---|---|
| 总开发窗口 | 6 小时 | 启动时记录开始/截止时间，剩余 30 分钟进入收尾 |
| 编码 Agent 并行 | 单 Agent | 不自行启动多个修改同一仓库的 Agent |
| 新付费模型调用 | 0；已有明确授权则沿用 | 发现 API Key 不等于获得消费授权 |
| 正式评测 | 0 个正式 run | 只准备代码/配置，不提前看竞赛 holdout 分数 |
| 训练并发/内部线程 | 1 / 1 | 避免开发验证相互抢占资源 |
| 整夜 estimator fit 尝试 | 上限 400 | 包括 smoke、修复重跑和真实 API smoke；按实际累计 |
| 单个 smoke run | 最多 90 fits、20 个训练作业、40 分钟 | 含基线、标定、探索、确认、重训；启动前校验可行 |
| 单 CV job | 最多 120 秒 | 同时不得超出 run 剩余时间/夜间截止时间 |
| 单依赖安装尝试 | 最多 10 分钟 | 排查后最多再试一次；不得整夜循环安装 |
| 单个公共数据获取 | 最多 10 分钟、100 MB | 超时走已声明回退；不批量下载全部竞赛 |
| 同一明确失败原因 | 最多 2 次有变化的修复尝试，或 30 分钟 | 达到界限换路径/记录阻塞；不重复原命令碰运气 |
| 资源不足/磁盘错误 | 停止新增重型动作 | 先保全代码和日志，说明未完成项 |

这里的工程修复次数，与产品内“单规格最多一次 LLM 修复”是不同计数；产品规则不能因调试而放宽。重新运行训练要计入夜间 400 fits 总额，不能通过新建 run_id 清零。

夜间 smoke 建议固定：5 折、3 套基线标定、最多 4 个探索规格、3 套候选/基线确认、一次最终重训。完整路径为 `5 + 15 + 20 + 30 + 1 = 71 fits`；预算 90 为失败和少量额外验证留余量。基线、种子和规则必须搜索前冻结；正式配置保持方案原定 5 套标定，不能用 smoke 配置冒充正式实验。

上限并非要求消耗到上限。优先在小型真实数据集验证，机械边界测试使用小 fixture；没有新修改和新疑点时，不反复跑全量训练。

## 4. 九个阶段任务

时间盒合计 360 分钟，为推进参考而非完成承诺。提前完成进入下一项；超时先保证 A 层依赖，压缩条件项，最后 30 分钟不新增功能。

### N00：建立现场快照和执行记录（15 分钟）

- [ ] 读取适用 AGENTS.md、两份方案、本清单；记录 git status、已有文件和适用约束。
- [ ] 保存启动时未提交修改清单。当前已知有原设计文件删除与 v3 文档未跟踪状态，以现场为准；不得恢复、覆盖或提交用户已有变更。
- [ ] 检查可用 Python/uv、CPU/RAM、依赖和现有环境；优先使用已有运行时和项目虚拟环境。
- [ ] 初始化 `docs/night-run/STATUS.md`、`DECISIONS.md`、`BLOCKERS.md` 和 `logs/`，记录启动/截止时间及资源上限。
- [ ] 环境只检查凭证是否存在和配置是否完整，不把凭证值打印到日志。

**验收：** 知道从哪里接续、实际允许做什么；没有因先做大范围环境改造而耗尽夜间窗口。

### N01：最小工程与严格 Schema（30 分钟）

- [ ] 创建/补齐 pyproject、锁文件、包入口、测试目录、必要的 `.gitignore` 与 `.env.example`。
- [ ] 用方案的严格类型实现 ExperimentSpec、ProposalBatch、EvaluationRecord、ProtocolSpec、TaskContract。
- [ ] 实现规范化哈希、两候选数量限制、非法参数/额外字段拒绝、目标列排除和证据引用校验。
- [ ] 确定统一 CLI：`doctor`、`research`、`reproduce`、`replay`。后续才可执行的命令不能先宣称可用。

**验收：** 核心模块可导入；有效/非法 Schema 样例测试通过；LLM 不能生成最终程序裁决。

### N02：预算与事件最小实现（45 分钟）

- [ ] 实现单写者 JSONL 与每实验 JSON；事件记录序号、动作 ID、时间和产物引用。
- [ ] 实现 reserve/settle/unknown，覆盖请求、Token、训练作业、fit、时间和收尾额度。
- [ ] 基线/标定前建立同一 run 账本，不在冻结契约后清零。
- [ ] 失败缺 usage 不计成零；重复结算拒绝；未知是否执行的动作不得盲目重发。
- [ ] 保存临时文件后原子替换，再追加完成事件；配置和日志脱敏。

**验收：** 预算不足时执行器未被调用；失败与未知消耗保留；事件可重读并定位实验事实。

### N03：真实数据、Pipeline 与 Runner（60 分钟）

- [ ] 先用可本地加载的小型二分类数据打通训练。可使用 `sklearn.datasets.load_breast_cancer` 作工程 smoke，该加载器提供真实二分类数据。[R4]
- [ ] Bank Marketing 可获取时实现适配器和预测时点规则；下载受阻不阻断训练器开发。
- [ ] 实现稳定 row_id、数据哈希、分层 CV 清单；只传开发数据到 Runner。
- [ ] 实现数值/类别预处理、LR/RF/HGB 三族，以及 TF-IDF 的小样本单元/集成测试。真实文本题不可用时，文本 fixture 必须标为测试材料。
- [ ] 所有拟合在训练折内；HGB 文本缺 SVD、log1p 越界、目标入特征、编码后内存过大均拒绝。
- [ ] 子进程执行有超时和退出状态，fit 开始即计数；仅清理本任务启动且可识别的子进程。

**验收：** 至少一次真实模型 fit 成功，保存逐折指标/规格/日志；超时路径可验证。不能只写 mock Runner。

### N04：随机搜索、标定、裁决与确认（45 分钟）

- [ ] 同一采样器用于随机基线和未来工具调度，固定 RNG 与合法空间。
- [ ] 先固定 ProtocolSpec，再训练有效基线和噪声标定，最后冻结 TaskContract。
- [ ] noise_floor 使用标定分数样本标准差，min_effect 为它与预设工程下限的最大值。
- [ ] 探索做同折配对差；最终确认用不同切分 seed，并固定对照初始基线。
- [ ] 区分 candidate_pass、confirmed_pass、not_met、inconclusive、invalid。
- [ ] 实现选一个候选确认、确认不通过回退基线、无候选时说明原因的流程。

**验收：** 无 LLM 也能完整跑一个真实数据 smoke；结果规则可复算；更换的是确认切分而不只是训练 seed。

### N05：Controller 离线闭环（60 分钟）

- [ ] 实现状态机、合法性/去重/预算筛选、双候选选择、明确停止和失败终态。
- [ ] ScriptedProposer 只作为测试替身，经过与真实接口相同的 ProposalBatch 校验；结果写 `proposal_source=scripted`。
- [ ] 至少两轮测试：第一轮真实训练，第二轮输入确实包含第一轮结果，继续真实训练；不是只生成两份静态输出。
- [ ] 实现核心的空候选上限、一次规格修复限制、收尾预留，以及不泄露隐藏信息的 AgentContext。
- [ ] 若时间足够，加入工具调度、Critic incident 去重的规则测试；不能为了演示强制制造虚假事件。

**验收：** 真实 Runner 与 Controller 连通；重复/非法/预算不足可停止；脚本化轨迹在报告中醒目标识，不称真实 LLM 结果。

### N06：真实 Gateway 代码与条件 smoke（45 分钟）

- [ ] 实现 PydanticAI Gateway、输出 Schema、提示词、脱敏请求记录和真实请求计量入口；框架/SDK 隐式重试关闭或统一计量。
- [ ] 不依赖凭证的测试用官方/受控测试模型或 fixture 验证解析、修复与错误归账；测试类型单独标注。
- [ ] 仅当用户明确授权新 API 消费、配置齐全且限额可执行时，做最终 Schema 的真实接口 smoke。
- [ ] 通过后在预算内完成两轮真实 Proposer→真实 Runner→反馈；最多完成一次成功的真实闭环 smoke，不反复追求更高分。
- [ ] 无凭证/无预算/价格不可确认/接口失败达到界限：标记真实验证 `blocked_external`，继续 N07/N08；代码实现仍尽量完成。

**验收：** 区分“Gateway 代码已测”“真实接口已通过”“真实闭环已完成”三个状态；不可混为完成。

### N07：冻结交付、报告和复现（30 分钟）

- [ ] 对选定规格在全开发集 refit，保存 Pipeline、规格/依赖/数据哈希；失败标为 delivery_failed。
- [ ] 生成从真实账本填充的 Markdown 报告，列出初始分、探索最佳、确认结论、交付规格、成本和限制。
- [ ] 实现固定规格 reproduce 与只读 replay；回放不得启动训练或模型请求。
- [ ] 最终评测接口只允许冻结后的交付；不在夜间查看正式 Kaggle holdout。OS 级隔离尚未验证时准确说明仅实现应用层边界。
- [ ] 若还剩时间，准备四组差异配置和正式矩阵预登记器，不实际启动正式矩阵。

**验收：** 至少一个可复训的真实模型产物与报告；不是某折模型；回放零新增请求/fit。

### N08：整体验证与晨间交接（预留 30 分钟）

- [ ] 运行 lint、核心离线测试、CLI help/doctor 和一个端到端 smoke；修复本轮引入的失败。
- [ ] 原有基准失败、外部条件跳过、新增失败分别报告；不能通过删除测试、伪造日志或统一 skip 让结果变绿。
- [ ] 从锁文件进行新虚拟环境安装检查；若网络/时间不足，保留精确未验证范围，不声称新环境复现成功。
- [ ] 核对新增文件、diff、敏感信息和正在运行的自有进程；不执行 git add -A、commit/push、reset --hard 或 git clean。
- [ ] 写 `docs/night-run/HANDOFF.md`，更新状态与阻塞，列出用户起床后可复制的已验证命令。
- [ ] 停止本任务遗留进程；完成即结束，未完成则按约定时间暂停 Goal，保留真实状态。

**验收：** 起床后仅阅读 HANDOFF 就能知道成果、证据、限制和下一步；无需翻整夜聊天找信息。

## 5. 阻塞处理：继续做什么

| 阻塞 | 自动执行的替代路线 | 不得作出的声明 |
|---|---|---|
| API Key/模型配置/预算缺失 | 完成 Gateway 代码、离线解析测试、真实 ML + ScriptedProposer 控制流 | 已完成真实 LLM 闭环 |
| Kaggle 权限/规则未就绪 | 仅准备适配器/评分接口，用本地真实数据验证核心引擎 | 官方评分已通过/达到排行榜名次 |
| Bank 下载失败 | 使用 sklearn 内置真实二分类数据做工程 smoke，清楚注明替代 | Bank 业务约束或泛化已验证 |
| PydanticAI 不兼容 | 依据官方 API 排查并固定可用依赖；不影响 ML 核心的依赖分开安装 | 返回固定 JSON 的 stub 是真实模型接入 |
| 某模型/文本组合失败 | 修正确有 bug 的兼容路径；超预算/本来非法则拒绝并记原因 | 静默换规格后仍称同一次实验 |
| 权限审批被拒/必须人工授权 | 记录具体动作与原因，继续无需该权限的工作 | 已绕过限制或替用户同意新条款 |
| 核心链路失败 | 优先修依赖它的核心；可独立做测试/文档，相关下游标 blocked_dependency | 依赖没通却把全部后续标完成 |
| 连续相同失败 | 两次有实质变化的尝试后改路径；不再相同重试 | 大量重试不计成本 |
| 配额/连接中断 | 尽可能保存当前状态；恢复时读状态/账本核对再继续 | 一定自动续跑或保证完成 |
| 临近截止 | 停止扩大功能，验证已有成果并交接 | 通过放宽验收假装完成 |

## 6. 持久状态和交接格式

工程 Agent 启动后创建以下文件；本次只规定格式，不预先填写已完成状态。

```text
docs/night-run/
├── STATUS.md             # 当前阶段、各项状态、开始/截止时间
├── DECISIONS.md          # 实施取舍、理由、影响范围
├── BLOCKERS.md           # 证据、尝试、替代路线、缺失输入
├── HANDOFF.md            # 起床后首先阅读
└── logs/                 # 命令、退出码、脱敏输出；不默认入库
```

STATUS 每完成一个阶段或改变关键决策时更新，并在仍有工具执行的情况下约每 15 分钟保存一次检查点；这不是另建定时自动任务。字段至少为：

```text
started_at / deadline_at / current_stage / last_verified_at
accepted_limits / fits_attempted / known_api_cost / unknown_api_cost
stage_status: pending | in_progress | passed | failed | blocked_external |
              blocked_dependency | deferred
current_changes / last_validation / next_action
```

HANDOFF 必须包含：

1. **交付级别**：A 是否完成，B 是否完成，C 完成哪些；没有完成的明确说没有完成。
2. **已验证命令**：安装、测试、真实数据 smoke、报告查看、复训；给出绝对路径、参数和结果。
3. **证据**：run_id、实验数/fit 数、实际模型请求数、费用/未知项、日志路径。
4. **当前代码变更**：新增/修改文件、与启动时已有变更的区别。
5. **阻塞**：缺什么输入、已经试过什么、白天第一步怎么解除。
6. **质量说明**：失败/skip 测试、隔离层级、未验证真实 API、是否用了替代数据。
7. **后续优先三件事**：按依赖排序，避免另写泛泛的待办。

## 7. 最低验收与可执行检查

建议实现后使用以下命令名称；实际接口有合理变化时同步 README/HANDOFF，不能把下面的建议命令直接当作成功记录。

```powershell
uv sync --frozen
uv run ruff check .
uv run pytest -q -m "not live_api and not kaggle"
uv run python -m budgetlab.cli --help
uv run python -m budgetlab.cli doctor --config configs/night_smoke.yaml
uv run python -m budgetlab.cli research --config configs/night_smoke.yaml --system random_search
uv run python -m budgetlab.cli research --config configs/night_smoke.yaml --system scripted_smoke
uv run python -m budgetlab.cli reproduce --run-id ACTUAL_RUN_ID
uv run python -m budgetlab.cli replay --run-id ACTUAL_RUN_ID
git diff --check
```

测试必须覆盖：严格 Schema、目标/非法列、固定切分、fit 计数、预算拦截、未知 usage、重复结算、重复候选、超时、确认回退、最终 refit、脚本化两轮反馈、回放零调用。真实 API/Kaggle 测试使用独立 marker；离线核心测试不得以缺 Key 为理由被跳过。`git diff --check` 不覆盖未跟踪文件，新增代码仍需通过 lint/测试和文件清单检查。

输出“通过”须有对应执行证据，不以代码量、文件数、目录齐全或一个空 pytest 运行替代完成标准。

## 8. 官方运行说明与参考

本清单的 6 小时、预算、阶段和验收是针对本项目的工程安排，不是平台保证。

- [R1] 本地任务的机器/应用运行要求：`https://learn.chatgpt.com/docs/automations?surface=app`
- [R2] 桌面设置与防休眠的平台说明：`https://learn.chatgpt.com/docs/reference/settings`
- [R3] Goal 的完成条件、续跑与权限边界：`https://learn.chatgpt.com/docs/long-running-work`
- [R4] scikit-learn 内置二分类 smoke 数据：`https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_breast_cancer.html`
- [R5] 长任务的文件化规范、分阶段验证和状态记录：`https://developers.openai.com/blog/run-long-horizon-tasks-with-codex`

