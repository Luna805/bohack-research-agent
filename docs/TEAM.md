# BudgetLab 四人分工与多人开发规范

> 生效：2026-11-14 10:30（北京时间）起 · 10:35 增加第 4 节「对话式研究页」· 提交截止 11/15 08:00
> 配套文档：模块之间怎么对接见 [`INTERFACES.md`](INTERFACES.md)；编码约束见 [`../AGENTS.md`](../AGENTS.md)；进度见 [`HANDOFF.md`](HANDOFF.md)。

## 1. 分工总览

核心原则：**每个文件只有一个负责人**。改别人的文件需要先在群里打招呼；新功能尽量放进自己的新文件。

| 角色 | 一句话职责 | 建议人选（可调整） | 交付给谁 |
|---|---|---|---|
| **A · Agent 与模型** | 让真实 LLM 提出好的实验假设，并把每一个 Token 记清楚 | chier1（写过真实 HTTP 适配和 check_model） | B（提案接口）、C（真实 LLM 的 run） |
| **B · 研究引擎** | 维护研究主循环：预算、裁决、停止、冻结；保证 `main` 始终是绿的 | Luna805（v3 方案和夜间引擎的作者） | A、C（`run_research` 和 run 目录格式） |
| **C · 实验与评测** | 准备数据，批量跑对照矩阵，产出可信的成绩表 | yirran（已经准备好数据，有 CI 推送权限；兼任协调人） | D（`results/` 目录） |
| **D · 展示与材料** | 做「对话式研究页」：给一个机器学习任务就能在网页上完整跑一遍并追问；再加报告、PPT 和演示 | 第四位同事 | 评委 |

**协调人**（建议 C 兼任）负责：维护 `HANDOFF.md` 的进度表、组织每次合流、打冻结 tag、最终提交。

**跨角色任务「对话式研究页」**由 D 牵头，A、C 配合，详见第 4 节。它是演示的主入口，但**不能影响 20:00 的正式成绩**：网页只调用冻结后的同一份引擎，不改引擎行为。

## 2. 文件归属（避免冲突的关键）

| 角色 | 只能由该角色修改的文件 | 新建文件放在哪里 |
|---|---|---|
| A | `budgetlab/proposers.py`、`tests/test_llm_http.py`、各配置文件里的 `llm:` 段 | `budgetlab/agents/`（协议理解 `protocol_agent.py`）、`budgetlab/qa/agent.py`（问答 Agent）、`tests/test_agent_*.py`、`tests/test_qa_agent.py`、`configs/llm-*.yaml` |
| B | `controller.py`、`state.py`、`budget.py`、`evaluator.py`、`schemas.py`、`contracts.py`、`runner.py`、`worker.py`、`pipeline.py`、`search.py`、`ledger.py`、`provenance.py`、`cli.py`、`tests/conftest.py` 及对应测试；**`pyproject.toml`、`uv.lock`、`.github/`** | `budgetlab/memory/`（经验库，P1）、`tests/test_engine_*.py` |
| C | `budgetlab/tasks/`（含场景卡）、`data.py`、`profile.py`、`budgetlab/evaluation/`、`configs/bank_marketing.yaml` 中除 `llm:` 外的部分 | `budgetlab/benchmark.py`、`budgetlab/tasks/csv_task.py`（通用 CSV 适配器）、`configs/benchmark/`、`results/`、`data/uploads/`（不入库）、`tests/test_benchmark*.py`、`tests/test_csv_task.py` |
| D | `reporting.py`、`README.md` | `budgetlab/ui/`（页面、后台启动器、步骤卡片）、`budgetlab/qa/evidence.py`、`budgetlab/qa/faq.py`、`ui_state/`（不入库）、`docs/presentation/`、`slides/`、`tests/test_ui*.py`、`tests/test_qa_faq.py` |
| 协调人 | `docs/HANDOFF.md`、`docs/TEAM.md`、`docs/INTERFACES.md`、`AGENTS.md` | — |

容易冲突的地方，统一这样处理：

- **命令行**：`cli.py` 归 B。新功能不加子命令，而是做成独立入口，例如 `python -m budgetlab.benchmark`、`streamlit run budgetlab/ui/app.py`。
- **Schema**：`schemas.py` 归 B。新功能的数据结构定义在自己的模块里；要改已有字段，先找 B。
- **依赖**：只有 B 改 `pyproject.toml` 和 `uv.lock`，其他人有需要先在群里提。UI 需要的 `streamlit`、`plotly` 已经放进 `ui` 可选依赖，用 `uv sync --frozen --extra dev --extra llm --extra ui` 安装。
- **配置**：自己做实验时新建 `configs/<角色>-*.yaml`，不要改共享的 `bank_marketing.yaml`。
- **测试夹具**：`conftest.py` 归 B；其他人把夹具写在自己的测试文件里。
- **开发日志**：每人只写自己的 `docs/devlog/<角色>.md`，`HANDOFF.md` 只由协调人更新。
- **`budgetlab/qa/` 目录**：D 负责 `__init__.py`（共用的 `QAAnswer` 定义，改动需要 A 点头）、`evidence.py`、`faq.py`；A 只写 `agent.py`。双方通过 INTERFACES 第 8.4 节对接。
- **`.gitignore`**：第一个创建 `ui_state/` 或 `data/uploads/` 的人，顺手把它加进 `.gitignore`（只追加，不改别的行）。

## 3. 每个角色的任务清单

### A · Agent 与模型
1. **（阻塞项）真实接口门禁**：拿到模型信息后，填 `.env`，在 `configs/llm-dev.yaml` 里设正数的 LLM 预算，跑 `probe-llm`。tool 模式不通就依次试 `native`、`prompted`。如果模型有思考模式，补上 `extra_body` 支持并关闭思考。
2. 在 Bank 上跑 2–3 次 `--system budgetlab --proposer llm`，看提案质量：有没有引用证据、有没有重复、有没有用到 `pdays` 这类语义信息。
3. 根据结果调整 `build_context` 和提示词，目标是上下文更短、提案更准。每次改动都要附上前后的 Token 对比。
4. **协议理解 Agent**（原 P1，现在升级为对话式研究页的必需件）：输入一句话任务描述加字段画像（不带可用性标注），输出 `DraftProtocol`（INTERFACES 8.1），包括目标列、正类、预测时点、指标、每个字段能否使用及理由、需要向用户确认的问题。放在 `budgetlab/agents/protocol_agent.py`。在 Bank 上对照场景卡打分，记录首次正确率和成本。
5. **问答 Agent** `budgetlab/qa/agent.py`：用 D 的证据工具（INTERFACES 8.4）回答开放问题，输出带证据引用的 `QAAnswer`；计量和研究预算分开。
6. 没有 API 时：用 `FunctionModel` 和本地假服务器继续做第 3–5 项。

### B · 研究引擎
1. 保持 `main` 是绿的；审核所有改动共享接口的提交。
2. 配合 A：A 需要新的状态信息时，由 B 在 `state.py` 或 `controller.py` 里提供，再由 A 放进上下文。
3. 配合 C：保证 `run_research()` 的签名和 run 目录格式稳定（见 INTERFACES 第 1、2 节）。
4. **P1 经验库**：放在 `budgetlab/memory/`。每个 run 结束时，从账本里抽取"条件 → 动作 → 效果 → 证据"写入草稿；新 run 开始时按画像条件匹配，最多 3 条传给 A 的上下文（字段 `lessons`）。
5. 正式矩阵开跑前做一次全量回归（Bank 上三个系统各跑一次），并检查报告里的数字。

### C · 实验与评测
1. **对照矩阵脚本** `python -m budgetlab.benchmark --matrix configs/benchmark/<名字>.yaml`：按"任务 × 系统 × 重复次数"依次跑 `run_research`，跑完对每个 run 统一调用 `evaluate_frozen_run`，按 INTERFACES 第 5 节的格式写入 `results/<matrix_id>/`。
2. 先用 `--proposer scripted` 跑小矩阵（1 次重复）打通流程，再接入 A 的真实 LLM。
3. 第二个任务：MLE-bench 最多试 1 小时；不行就换一个公开的二分类数据集（带场景卡），保证结论不只建立在一个数据集上。
4. **冻结后在一台机器上跑正式矩阵**，跑完把结果提交到 `results/`。
5. 写数据和评测相关的限制说明，例如随机切分偏乐观，交给 D 放进报告。
6. **通用 CSV 适配器** `budgetlab/tasks/csv_task.py`（给对话式研究页用）：接收用户上传的 CSV 和人确认过的场景卡，注册一个可以 `prepare` 和 `run_research` 的任务（INTERFACES 8.2）。只支持二分类、≤10 万行、≤200 列；不满足条件时给出清楚的拒绝理由。

### D · 展示与材料
1. **对话式研究页** `budgetlab/ui/app.py`（Streamlit），按第 4 节分三个阶段交付。保底版必须在 16:00 前可用。
2. **对比页**：同一个应用里另开一个页签，读取 `results/`，展示各系统的对比表，以及最优分对累计 Token 和对时间的曲线。
3. 改进 `reporting.py` 的单 run 报告，让评委 1 分钟内能看懂。
4. 写 README 终稿、项目说明、PPT 和 3–5 分钟的演示脚本（以对话式研究页为主线），录好备用视频。**所有成绩数字只能来自 `results/`。**

## 4. 跨角色任务：对话式研究页

**目标**：在网页上用一句话交代一个机器学习任务（附带数据），系统像对话助手一样一步步展示整个研究过程，最后给出结论，并能接着追问。

### 4.1 用户看到的流程

1. **交代任务**：选择预设数据集或上传 CSV，用一句话描述，例如"打电话之前预测客户会不会订存款"。
2. **确认协议**：系统给出协议草稿，包括目标列、正类、指标、预测时点，以及哪些字段要排除、为什么。用户修改或确认。**不确认就不能开跑。**
3. **开跑**：人点"开始研究"按钮后，后台子进程运行现有引擎。页面实时把事件渲染成步骤卡片：数据画像、基线、门槛标定、每轮提案（两个候选和各自的假设）、训练、裁决、换方向、确认、冻结交付。右侧显示进度清单和"最优分对 Token"曲线。
4. **结论**：显示提升、成本、确认状态；提供一个按钮做 holdout 一次性评测。
5. **追问**：快捷问题按钮不花 Token，由程序从账本生成答案；开放问题交给问答 Agent，回答附证据卡片，数字逐一核对。

### 4.2 分工与阶段

| 阶段 | 截止 | 内容 | 负责 |
|---|---|---|---|
| ① 保底版 | **16:00** | 选预设任务（Bank、breast_cancer），表单填预算，后台跑完整流程，显示步骤卡片和结论，holdout 评测按钮，0 Token 快捷问答，证据卡片 | D |
| ② 对话版 | **19:30** | 入口换成对话：一句话描述加数据 → `DraftProtocol` → 人确认 → 写场景卡 → 开跑；开放问题交给问答 Agent | D（页面）、A（协议 Agent、问答 Agent）、C（CSV 适配器） |
| ③ 打磨 | 20:00 之后 | 体验、文案、录演示视频；可以用冻结版本的代码跑演示 | D 主做，A 配合 |

### 4.3 必须遵守的约束

- **训练只在后台子进程里跑**（`python -m budgetlab.cli research ...`）。页面只负责读进度，刷新页面不能重复启动训练。
- **聊天里的大模型不能触发任何操作**：开跑、评测、改配置都只能由人点按钮。大模型只负责起草协议和解释结果。
- **字段可用性由人最终确认**：大模型的草稿只是建议，确认后的场景卡才会进入契约，草稿和最终版都要保存。
- **没有 LLM 时**：对话版降级成"表单选数据 + 手填协议 + scripted 提案"，页面上要明确标注"未使用 LLM"。
- **任意 CSV 只支持二分类**：多分类、回归和时间切分在上传时就拒绝，并说明原因。
- **网页跑出来的 run 不进正式成绩**：正式成绩只来自 C 在冻结版本上跑的 `results/final-*`。网页的 run 写到 `runs/` 下，`run_config.json` 里的 `system` 和 `proposal_source` 照常记录。

### 4.4 验收标准

- 保底版：在一台干净机器上执行 `streamlit run budgetlab/ui/app.py`，选 Bank 和 scripted，点开始，约 2 分钟内看到完整的步骤卡片、结论和 holdout 分数；点 3 个快捷问题，都能得到带证据卡片的回答。
- 对话版：用一句话描述 Bank 任务，协议草稿能正确排除 `duration`；上传一个新的二分类 CSV，能走完全程。

## 5. 时间线与合流点（11/14 → 11/15）

| 时间 | 内容 | 每人必须做到 |
|---|---|---|
| 10:30–11:00 | 开工 | `git pull`、`uv sync`、读完本文和 INTERFACES、建好自己的分支 |
| **13:00 合流 1** | 第一批合进 `main` | A：`probe-llm` 结论（通过／失败原因／缺凭证）；B：经验库数据结构草案；C：小矩阵在 Bank 上跑通并产出 `results/dev-*`；D：页面能在后台启动一次 run，并实时显示步骤卡片 |
| **16:00 合流 2** | 第二批合入 | A：真实 LLM 的 Bank run；B：经验库能写能读（或明确放弃）；C：汇总表、第二个任务；**D：对话式研究页保底版完成（第 4.4 节验收）**；A：协议 Agent 能出 `DraftProtocol` 草稿；C：CSV 适配器可用 |
| **19:30 代码冻结** | 只修阻塞问题 | B 做全量回归；协调人确认 CI 是绿的；对话版没完成就用保底版演示 |
| **20:00** | 打 tag `benchmark-freeze`，C 开跑正式矩阵 | 正式矩阵期间不要往 `main` 推代码（文档除外） |
| 20:00–00:30 | 正式运行 | D 打磨对话式研究页（③）并完成 PPT 结构；A、B 写项目说明的技术部分 |
| 00:30–03:00 | 结果入库，生成图表 | C 提交 `results/`；D 把数字填进页面和 PPT |
| 03:00–05:30 | 录演示、彩排 | 全员 |
| 05:30 | 功能冻结 | 只改错字和链接 |
| 07:30 | 提交 | 协调人提交仓库链接、PPT 和项目说明 |

如果 LLM 接口一直拿不到：A 继续做协议理解和上下文优化；正式矩阵改成"随机搜索 vs BudgetLab（scripted）"，并在材料里如实说明。

## 6. 多人开发规范

### 6.1 分支与合并
- 每人在自己的分支上开发：`<角色>/<主题>`，例如 `a/probe-llm`、`c/benchmark`、`d/ui`。
- 一个分支只做一件事，做完就合进 `main`，最好不超过 2–3 小时一合。合并前先 `git pull --rebase origin main`，在本地跑 `pytest -q` 和 `ruff check .`。
- 合并方式：推送分支，在 GitHub 上开 PR，CI 是绿的再合（单人自合也可以）。改了 INTERFACES 里定义的接口，需要被影响的角色点头。
- 禁止 `push --force` 到 `main`；禁止直接在 `main` 上大改。
- 不要在 GitHub 网页上传整包文件（之前 `research-agent-hyf` 分支就是这样坏掉的）。统一用 git 命令提交。

### 6.2 接口变更
- 接口指的是 INTERFACES.md 里列出的东西：run 目录格式、`run_research` 签名、Proposer 协议、场景卡格式、`results/` 格式，以及对话式研究页的对接（第 8 节）。
- **只加字段，不改名、不删字段**。确实要破坏性修改时，先在群里说，同时提升对应的版本号（例如 `summary_version`），并同步更新 INTERFACES.md。

### 6.3 冲突处理
- 冲突发生在别人的文件里：保留对方的版本，再把自己的改动以最小方式重新加上，然后通知对方。
- 冲突发生在 `uv.lock`：不要手工合并。由 B 重新执行 `uv lock` 生成。

### 6.4 每次干完活
1. 在 `docs/devlog/<角色>.md` 里追加一条：时间、做了什么、怎么验证的（命令和 run_id）、遇到的问题、下一步。
2. 在群里说一句："已合入 xxx，影响 yyy"。

### 6.5 AI 代理
- 每个人可以各自使用 AI 代理，代理会自动读 `AGENTS.md`。给代理布置任务时说清楚你的角色，并要求它只改你的文件。
- 代理的产出由人负责审核后再合并。
