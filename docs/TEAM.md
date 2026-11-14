# BudgetLab 四人分工与多人开发规范

> 生效：2026-11-14 10:30（北京时间）起· 提交截止 11/15 08:00
> 配套文档：模块之间怎么对接见 [`INTERFACES.md`](INTERFACES.md)；编码约束见 [`../AGENTS.md`](../AGENTS.md)；进度见 [`HANDOFF.md`](HANDOFF.md)。

## 1. 分工总览

核心原则：**每个文件只有一个负责人**。改别人的文件需要先在群里打招呼；新功能尽量放进自己的新文件。

| 角色 | 一句话职责 | 建议人选（可调整） | 交付给谁 |
|---|---|---|---|
| **A · Agent 与模型** | 让真实 LLM 提出好的实验假设，并把每一个 Token 记清楚 | chier1（写过真实 HTTP 适配和 check_model） | B（提案接口）、C（真实 LLM 的 run） |
| **B · 研究引擎** | 维护研究主循环：预算、裁决、停止、冻结；保证 `main` 始终是绿的 | Luna805（v3 方案和夜间引擎的作者） | A、C（`run_research` 和 run 目录格式） |
| **C · 实验与评测** | 准备数据，批量跑对照矩阵，产出可信的成绩表 | yirran（已经准备好数据，有 CI 推送权限；兼任协调人） | D（`results/` 目录） |
| **D · 展示与材料** | 把结果做成看得懂的界面、报告、PPT 和演示 | 第四位同事 | 评委 |

**协调人**（建议 C 兼任）负责：维护 `HANDOFF.md` 的进度表、组织每次合流、打冻结 tag、最终提交。

## 2. 文件归属（避免冲突的关键）

| 角色 | 只能由该角色修改的文件 | 新建文件放在哪里 |
|---|---|---|
| A | `budgetlab/proposers.py`、`tests/test_llm_http.py`、各配置文件里的 `llm:` 段 | `budgetlab/agents/`（例如协议理解 `protocol_agent.py`）、`tests/test_agent_*.py`、`configs/llm-*.yaml` |
| B | `controller.py`、`state.py`、`budget.py`、`evaluator.py`、`schemas.py`、`contracts.py`、`runner.py`、`worker.py`、`pipeline.py`、`search.py`、`ledger.py`、`provenance.py`、`cli.py`、`tests/conftest.py` 及对应测试；**`pyproject.toml`、`uv.lock`、`.github/`** | `budgetlab/memory/`（经验库，P1）、`tests/test_engine_*.py` |
| C | `budgetlab/tasks/`（含场景卡）、`data.py`、`profile.py`、`budgetlab/evaluation/`、`configs/bank_marketing.yaml` 中除 `llm:` 外的部分 | `budgetlab/benchmark.py`、`configs/benchmark/`、`results/`、`tests/test_benchmark*.py` |
| D | `reporting.py`、`README.md` | `budgetlab/ui/`、`docs/presentation/`、`slides/`、`tests/test_ui*.py` |
| 协调人 | `docs/HANDOFF.md`、`docs/TEAM.md`、`docs/INTERFACES.md`、`AGENTS.md` | — |

容易冲突的地方，统一这样处理：

- **命令行**：`cli.py` 归 B。新功能不加子命令，而是做成独立入口，例如 `python -m budgetlab.benchmark`、`streamlit run budgetlab/ui/app.py`。
- **Schema**：`schemas.py` 归 B。新功能的数据结构定义在自己的模块里；要改已有字段，先找 B。
- **依赖**：只有 B 改 `pyproject.toml` 和 `uv.lock`，其他人有需要先在群里提。UI 需要的 `streamlit`、`plotly` 已经放进 `ui` 可选依赖，用 `uv sync --frozen --extra dev --extra llm --extra ui` 安装。
- **配置**：自己做实验时新建 `configs/<角色>-*.yaml`，不要改共享的 `bank_marketing.yaml`。
- **测试夹具**：`conftest.py` 归 B；其他人把夹具写在自己的测试文件里。
- **开发日志**：每人只写自己的 `docs/devlog/<角色>.md`，`HANDOFF.md` 只由协调人更新。

## 3. 每个角色的任务清单

### A · Agent 与模型
1. **（阻塞项）真实接口门禁**：拿到模型信息后，填 `.env`，在 `configs/llm-dev.yaml` 里设正数的 LLM 预算，跑 `probe-llm`。tool 模式不通就依次试 `native`、`prompted`。如果模型有思考模式，补上 `extra_body` 支持并关闭思考。
2. 在 Bank 上跑 2–3 次 `--system budgetlab --proposer llm`，看提案质量：有没有引用证据、有没有重复、有没有用到 `pdays` 这类语义信息。
3. 根据结果调整 `build_context` 和提示词，目标是上下文更短、提案更准。每次改动都要附上前后的 Token 对比。
4. **P1 协议理解轨道**：给 LLM 不带可用性标注的字段表，让它提出该排除哪些列，程序对照场景卡打分，记录首次正确率和成本。放在 `budgetlab/agents/protocol_agent.py`。
5. 没有 API 时：用 `FunctionModel` 和本地假服务器继续做第 3、4 项。

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

### D · 展示与材料
1. **只读展示页** `budgetlab/ui/app.py`（Streamlit），只读 `results/` 和 `runs/`，不启动任何训练。三个区域：
   - 研究轨迹：每轮的候选、选择理由、裁决和方向变化；
   - 性能与成本：最优开发分数对累计 Token 和对时间的曲线，以及各系统的对比表；
   - 证据链：从结论回溯到假设、规格、日志和指标。

   回放模式要有明显标识。
2. 改进 `reporting.py` 的单 run 报告，让评委 1 分钟内能看懂。
3. 写 README 终稿、项目说明、PPT 和 3–5 分钟的演示脚本，录好备用视频。**所有数字只能来自 `results/`。**
4. 在 C 的正式结果出来前，用 `runs/` 里已有的 run 搭好页面结构，最后只需要换数据。

## 4. 时间线与合流点（11/14 → 11/15）

| 时间 | 内容 | 每人必须做到 |
|---|---|---|
| 10:30–11:00 | 开工 | `git pull`、`uv sync`、读完本文和 INTERFACES、建好自己的分支 |
| **13:00 合流 1** | 第一批合进 `main` | A：`probe-llm` 结论（通过／失败原因／缺凭证）；B：经验库数据结构草案；C：小矩阵在 Bank 上跑通并产出 `results/dev-*`；D：页面能读出一个 run 并显示表格和一条曲线 |
| **16:00 合流 2** | 第二批合入 | A：真实 LLM 的 Bank run；B：经验库能写能读（或明确放弃）；C：汇总表、第二个任务；D：三个区域都能用 |
| **19:30 代码冻结** | 只修阻塞问题 | B 做全量回归；协调人确认 CI 是绿的 |
| **20:00** | 打 tag `benchmark-freeze`，C 开跑正式矩阵 | 正式矩阵期间不要往 `main` 推代码（文档除外） |
| 20:00–00:30 | 正式运行 | D 用占位数据完成 PPT 结构；A、B 写项目说明的技术部分 |
| 00:30–03:00 | 结果入库，生成图表 | C 提交 `results/`；D 把数字填进页面和 PPT |
| 03:00–05:30 | 录演示、彩排 | 全员 |
| 05:30 | 功能冻结 | 只改错字和链接 |
| 07:30 | 提交 | 协调人提交仓库链接、PPT 和项目说明 |

如果 LLM 接口一直拿不到：A 继续做协议理解和上下文优化；正式矩阵改成"随机搜索 vs BudgetLab（scripted）"，并在材料里如实说明。

## 5. 多人开发规范

### 5.1 分支与合并
- 每人在自己的分支上开发：`<角色>/<主题>`，例如 `a/probe-llm`、`c/benchmark`、`d/ui`。
- 一个分支只做一件事，做完就合进 `main`，最好不超过 2–3 小时一合。合并前先 `git pull --rebase origin main`，在本地跑 `pytest -q` 和 `ruff check .`。
- 合并方式：推送分支，在 GitHub 上开 PR，CI 是绿的再合（单人自合也可以）。改了 INTERFACES 里定义的接口，需要被影响的角色点头。
- 禁止 `push --force` 到 `main`；禁止直接在 `main` 上大改。
- 不要在 GitHub 网页上传整包文件（之前 `research-agent-hyf` 分支就是这样坏掉的）。统一用 git 命令提交。

### 5.2 接口变更
- 接口指的是 INTERFACES.md 里列出的东西：run 目录格式、`run_research` 签名、Proposer 协议、场景卡格式、`results/` 格式。
- **只加字段，不改名、不删字段**。确实要破坏性修改时，先在群里说，同时提升对应的版本号（例如 `summary_version`），并同步更新 INTERFACES.md。

### 5.3 冲突处理
- 冲突发生在别人的文件里：保留对方的版本，再把自己的改动以最小方式重新加上，然后通知对方。
- 冲突发生在 `uv.lock`：不要手工合并。由 B 重新执行 `uv lock` 生成。

### 5.4 每次干完活
1. 在 `docs/devlog/<角色>.md` 里追加一条：时间、做了什么、怎么验证的（命令和 run_id）、遇到的问题、下一步。
2. 在群里说一句："已合入 xxx，影响 yyy"。

### 5.5 AI 代理
- 每个人可以各自使用 AI 代理，代理会自动读 `AGENTS.md`。给代理布置任务时说清楚你的角色，并要求它只改你的文件。
- 代理的产出由人负责审核后再合并。
