# BudgetLab 交接说明

> 更新：2026-11-14 13:55（北京时间）· main = `5c304ea`· 提交截止 11/15 08:00
> 开发规范见仓库根目录 [`AGENTS.md`](../AGENTS.md)（人和 AI 代理共用，Claude Code 通过 `CLAUDE.md` 自动读取）。

## 0. 先做这几件事

```bash
git pull                                         # main = 5c304ea
uv sync --frozen --extra dev --extra llm --extra ui   # ui 用于对话页（streamlit、plotly）
python -m budgetlab.cli prepare --task bank_marketing   # 下载 UCI 数据，切出密封 holdout（约 1 MB）
python -m pytest -q                              # 应为 52 passed（锁定环境，含 ui 依赖）
ruff check .
```

- 如果夜间版本之后你本地又改过 `controller.py`、`tests/conftest.py`，或者改过已删除的 `llm.py`，pull 时会冲突。冲突时以仓库版本为准，把你的改动重新加上去。
- `prepare` 用 urllib 下载，证书优先用 certifi 的（某些 macOS/pyenv 的 Python 缺系统证书）。如果需要代理，先设置 `HTTPS_PROXY`。下载失败时报错信息会给出手动下载的步骤：把 `bank-additional-full.csv` 放到 `data/raw/bank_marketing/bank-additional/` 下即可，程序会校验文件哈希。
- 以上命令已在干净的检出里验证过（uv sync → prepare → 测试 → ruff 通过）。对话页：`streamlit run budgetlab/ui/app.py`。

## 1. 现在到哪一步了

| 方案工作包 | 状态 | 说明 |
|---|---|---|
| W01 Schema | ✅ | 新增 `SentinelToMissing` 特征动作、HGB 的 `class_weight`、`LoopPolicy`、`CriticAdvice` |
| W02 预算与账本 | ✅ | 新增 `Budget.can_reserve()`（只试算，不改状态）和 `remaining()` |
| W03 数据与隔离 | ✅ | 任务适配器、场景卡、`prepare` 切出密封 holdout、开发集画像 `eda.json` |
| W04/W05 实验与裁决 | ✅ | 夜间版本基础上，随机搜索覆盖了特征动作 |
| W06 LLM 接入 | ⚠️ 代码完成 | Pydantic AI 提案器和 Critic，带预留与结算；走自建 httpx 客户端（SDK 重试关闭，usage 取自原始 HTTP 响应），已用本地假 OpenAI 服务器测过 tool/native/prompted 三种模式；**还没有对真实提供方请求过** |
| W07 主循环 | ✅ | 两个候选、筛查与去重、便宜时都跑、停止规则、工具搜索调度、重规划、方向归因 |
| W08 冻结与最终评测 | ✅ | `evaluate` 每个 run 只能评一次，第二次报错 |
| W09 正式对照矩阵 | ⚠️ 准备完成 | 矩阵脚本 `python -m budgetlab.benchmark`（串行、逐个 holdout 评测、可续跑、final 要求代码干净、LLM 开跑前检查）；`configs/benchmark/final.yaml`（LLM）和 `final-scripted.yaml`（备用）为草稿；**正式运行在 20:00** |
| W10 展示与材料 | ⚠️ 进行中 | 对话页第一版已合入（`budgetlab/ui/app.py`：示例任务、后台运行、0 Token 快捷问答）；CSV 上传、开放问答、PPT 未完成 |
| 第二个任务 | ✅ | UCI Adult（改为不做 MLE-bench），`configs/adult.yaml` |
| 通用 CSV 上传 | ✅ | `budgetlab/tasks/csv_task.py`；原始 Bank CSV 上传后的结果与内置任务完全一致 |
| P1 经验库 / 自定义特征 | ❌ | 未开始 |

**开发矩阵实测（f1_macro，脚本化提案，不是 LLM，各 1 次重复，机器空闲时运行）：**

| 任务 | 系统 | 基线 | holdout | 实验数 | 墙钟 |
|---|---|---|---|---|---|
| Bank | random_search | 0.6412 | 0.7099 | 18 | 97 s |
| Bank | budgetlab_no_schedule | 0.6412 | 0.7099 | 8 | 69 s |
| Bank | budgetlab | 0.6412 | 0.7099 | 12 | 82 s |
| Adult | random_search | 0.7792 | 0.8143 | 18 | 164 s |
| Adult | budgetlab_no_schedule | 0.7792 | 0.7941 | 6 | 135 s |
| Adult | budgetlab | 0.7792 | 0.8151 | 8 | 145 s |

Bank 的结果在 `results/dev-20261114T030336Z/`；Adult 那次运行的代码还没提交，所以结果没有入库。脚本化规则是照着 Bank 写的，在 Adult 上靠调度触发的随机搜索兜底。这些只证明管道能用，**不是成绩**；能否拉开差距，要看真实 LLM。

## 2. 代码地图

```text
budgetlab/
  tasks/__init__.py      任务注册表 + 下载/读取；cards/*.yaml 是场景卡（字段可用性的唯一来源）
  data.py                prepare（切 holdout）、load_development（只读开发集）、切分清单
  profile.py             开发集画像：类型、缺失、Top 值、分组正例率、哨兵值
  schemas.py             全部严格 Schema（extra=forbid, frozen）
  contracts.py           契约冻结、规格语义校验、spec_hash（列顺序不影响哈希）
  search.py              SpecSampler：random_search 系统和工具搜索共用的同一份代码
  pipeline.py / worker.py / runner.py   受控 sklearn Pipeline；子进程训练 + 超时
  evaluator.py           噪声地板标定、配对折差裁决、确认判定
  budget.py / ledger.py  预留/结算/未知；单写者 JSONL 事件
  state.py               ResearchState / ExperimentRecord / RoundRecord
  proposers.py           build_context、提示词、ScriptedProposer、PydanticAIProposer/Critic
  controller.py          setup → explore（3 种系统）→ finalize；metered_call 包住每次 LLM 调用
  evaluation/            唯一读取 data/sealed/ 的代码
  benchmark.py           对照矩阵（C）：python -m budgetlab.benchmark --matrix configs/benchmark/<名字>.yaml
  tasks/csv_task.py      通用 CSV 上传（C）：validate / register / config_for_upload
  ui/app.py、qa/         对话页与证据工具、快捷问答（D）
  reporting.py / cli.py  报告模板；命令行 prepare / research / evaluate / probe-llm / reproduce / replay
configs/bank_marketing.yaml   正式开发配置（预算、循环策略、LLM 设置都在这里）
configs/adult.yaml            第二个任务
configs/benchmark/            dev.yaml（两个任务的开发矩阵）、final.yaml、final-scripted.yaml
configs/night_smoke.yaml      乳腺癌数据的快速冒烟配置
```

三个系统：`random_search`（0 Token）、`budgetlab_no_schedule`（消融组：只有提案循环 + 去重 + 预算 + 停止规则）、`budgetlab`（在此基础上加工具搜索调度、重规划和按需 Critic）。

## 3. 分工与开发规范

**四人分工、文件归属、时间线和多人开发规范见 [`TEAM.md`](TEAM.md)；模块之间的接口见 [`INTERFACES.md`](INTERFACES.md)；编码约束见 [`AGENTS.md`](../AGENTS.md)。**

最容易出问题的几条：
- 只改自己角色的文件；新功能放进自己的新文件，新命令做成独立入口（`python -m budgetlab.<模块>`），不往 `cli.py` 里加。
- 在 `<角色>/<主题>` 分支上开发，CI 是绿的再合；不要在 GitHub 网页上传文件。
- 开发日志写到 `docs/devlog/<角色>.md`；本文件只由协调人更新。
- 正式结果必须来自非 dirty 的提交，并放在 `results/<matrix_id>/`。

## 4. 待办状态（协调人维护）

角色认领情况：C = yirran（兼协调人）；D = chier1（`d-ui` 已提交）；**A、B 尚未确认**。

| # | 任务 | 角色 | 负责人 | 状态 | 完成标准 |
|---|---|---|---|---|---|
| 0 | 启用 CI | 协调人 | yirran | ✅ `560db9b` | Ubuntu 和 Windows 两个任务都是绿的 |
| 1 | **确认 LLM 来源**：主办方是否提供模型、Key 和额度，还是自费 | 协调人 + A | – | ⏳ 等待原文 | 有群公告或手册原文；定下模型名、Base URL、单价 |
| 2 | 真实接口门禁：`probe-llm` | A | – | 待认领 | Schema 一次通过，usage 有值 |
| 3 | 真实 LLM 跑 Bank | A | – | 待认领 | 至少 2 轮真实提案→训练→反馈；Token 账目对得上 |
| 4 | 对照矩阵脚本 `python -m budgetlab.benchmark` | C | yirran | ✅ `165a031` | 产出符合 INTERFACES 第 5 节格式的 `results/<matrix_id>/` |
| 5 | **对话式研究页 · 主流程**（16:00）：一句话加数据 → 协议卡片确认 → 开跑，步骤卡片流式显示 → 总结、holdout、快捷问答；含无 LLM 兜底路径 | D（牵头）、A、C | chier1 | 🔄 第一版已合入 `5c304ea` | TEAM.md 4.4 的 16:00 验收（两条路径） |
| 5b | **对话式研究页 · 完善**（19:30）：开放问答、用一句话修改协议、CSV 上传、对比页签 | D、A、C | chier1 | 待开始 | TEAM.md 4.4 的 19:30 验收 |
| 6 | README、PPT、项目说明、录屏 | D（全员配合） | chier1 | 待开始 | 数字全部来自 `results/` |
| 7 | 协议 Agent `DraftProtocol`（16:00 前，主流程必需） | A | – | 待认领 | Bank 上能正确排除 `duration`；记录首次正确率和成本 |
| 8 | 问答 Agent `budgetlab/qa/agent.py` | A | – | 待认领 | 回答附证据，数字可核对，计量独立 |
| 9 | 通用 CSV 适配器 `budgetlab/tasks/csv_task.py` | C | yirran | ✅ `0ce4c7c` | 新的二分类 CSV 能 register → prepare → 跑通 |
| 10 | 第二个任务（改为 UCI Adult，不做 MLE-bench） | C | yirran | ✅ `c71a56f` | 场景卡 + prepare + 小矩阵能跑通 |
| 11 | 正式矩阵准备：LLM 开跑前检查、`final.yaml` 和 `final-scripted.yaml` | C | yirran | ✅ `7e1a629`（配置待 A 确认预算） | `--dry-run` 能给出检查结果 |
| 12 | 成绩表增加"对照随机搜索"和"成本效率"汇总 | C | yirran | ✅（`c/report-tables`，待推送） | 每个系统相对随机搜索的 Δholdout、ΔToken、Δ时间、胜负次数，以及每 1000 Token 带来的提升 |
| 13 | 演示用 CSV 和协议标准答案 [`examples/student_risk/`](../examples/student_risk/README.md) | C | yirran | ✅（`c/demo-csv`，待推送） | 给 D 现场上传用，给 A 的协议 Agent 打分用 |
| 14 | 数据与评测限制说明初稿 [`LIMITATIONS.md`](LIMITATIONS.md) | C | yirran | ✅ 初稿（待推送）；第 5 节等正式成绩出来后补 | 交给 D 放进报告和 PPT |
| 16 | holdout 置信区间与配对 bootstrap | C | yirran | ✅（`c/holdout-ci`，待推送） | `final_evaluation.json` 有 `holdout_ci95`；`comparison.json` 有配对区间 |
| 15 | **正式矩阵运行**（19:30 冻结、20:00 打 tag 开跑） | C | yirran | 待 20:00 | `results/final-*` 提交，代码版本非 dirty |
| P1 | `LLMSettings` 支持 `extra_body` | A | – | 待认领 | 选定的模型需要时再做 |
| P1 | 经验库 `budgetlab/memory/` | B | – | 待认领 | 能写能读，并完成一次有经验 vs 无经验的对照；做的话必须在冻结前定好快照 |

对话式研究页的流程和约束见 TEAM.md 第 4 节；时间线和合流点见第 5 节：13:00、16:00 两次合流；19:30 代码冻结；20:00 打 tag 并开跑正式矩阵。

## 5. 已知问题与限制

- **LLM 来源未确认**：项目里"主办方提供托管模型"的说法来自对群公告的转述，没有原文依据。
- 随机分层切分偏乐观：Bank 数据按时间排序，宏观经济列随时间变化，而本版不做时间切分。这一点场景卡里已经写明，报告也要写。
- `budget.seconds` 统计的是训练子进程时间，不是墙钟时间；墙钟时间看 `summary.wall_seconds`。
- LLM 预留按"估计输入 + 最大输出 ×（重试次数 + 1）"算，比较保守；`max_output_tokens` 默认 3000，非思考模型可以降到 1500–2000。
- 工具搜索的实验 ID（`tool-NN`）按实验总数编号，所以不连续，这是正常的。
- 训练运行在带超时的子进程里，这不是操作系统层面的沙箱，对外不要说成"安全沙箱"。
- `contracts.validate_proposal_batch` 只在测试里用到；主循环的筛查逻辑在 `controller.screen_candidates`。

## 6. 开发日志（截至 2026-11-14 10:30 的历史；之后写到 `docs/devlog/<角色>.md`）

新的在最上面。

### 2026-11-14 约 10:10–10:25 · yirran + Claude Code
- 做了：写好四人分工 `docs/TEAM.md` 和接口规范 `docs/INTERFACES.md`；新增 `docs/devlog/` 下每个角色的日志文件；`summary.json` 增加 `summary_version: 1`；`pyproject.toml` 增加 `ui` 可选依赖（streamlit、plotly），锁文件只新增、不改动已有版本。
- 问题：`0f1188f` 的 CI 在两个平台都失败。原因是锁定的 `openai` 3.x 依赖的是 `httpx2`，干净环境里没有 `httpx`，真实 LLM 调用会直接报 ModuleNotFoundError；开发机的 anaconda 环境里刚好装着 `httpx`，所以本地没暴露。已改为优先导入 `httpx2`，并在锁定环境里验证。

### 2026-11-14 约 09:55–10:10 · yirran + Claude Code
- 做了：从另一位同事的独立实现（chier1 / research-agent）移植两项：① LLM 调用改走自建 httpx 客户端，`openai` 的 `max_retries=0`，按请求钩子计数，usage 取自原始响应，缺 usage 的请求按保守估计记为 unknown；新增 `tests/test_llm_http.py`（本地假 OpenAI 服务器）。② 配对比较前的证据检查：worker 输出折指纹（每折验证行 ID 的哈希）、数据哈希和指标；`evaluator.comparison_problem` 检查完整性、有限性、切分种子、折指纹、数据和指标，不通过即 `invalid` 并写明原因；确认阶段每个切分都走同一检查（`confirmation/split-<seed>.json`）。
- 验证：33 passed，ruff 通过；Bank scripted run `20261114T020906Z-budgetlab-1725a4`：探索 12 个实验 0 个 invalid，三个确认切分均有效（Δ 0.067/0.071/0.066），confirmed_pass。
- 备注：GitHub 上的 `research-agent-hyf` 分支是网页半截上传（只有对方的 tests/scripts/pyproject，缺少其 budgetlab 模块），不要合并。

### 2026-11-14 约 09:45–09:55 · yirran + Claude Code
- 做了：`AGENTS.md` / `CLAUDE.md`、`results/` 目录约定；run 现在会记录 git 提交号、是否 dirty 和环境版本（`budgetlab/provenance.py`）。
- 验证：本地 17 passed，ruff 通过。
- 问题：CI 配置首次推送被拒（token 缺少 `workflow` 权限）；给 token 加上权限后推送成功（`560db9b`），首次运行 Ubuntu 和 Windows 均通过。
- 下一步：确认 LLM 来源。

### 2026-11-14 约 09:35–09:45 · yirran + Claude Code
- 做了：本交接文档；修复 macOS/pyenv 下下载数据的 SSL 证书问题（`df5a0f3`）。
- 验证：干净检出里依次跑通 `uv sync --frozen` → `prepare` → 17 passed → ruff 通过。

### 2026-11-14 约 09:05–09:30 · yirran + Claude Code
- 做了：Bank Marketing 适配器和场景卡、密封 holdout、数据画像、多轮主循环（三种系统）、Pydantic AI 提案器和 Critic 的计量、一次性 holdout 评测（`05c008b`）。
- 验证：17 passed；Bank 数据上 random_search 的 holdout 为 0.713，budgetlab（scripted）为 0.710，两者都是 confirmed_pass。
- 问题：脚本化提案器和随机搜索打平（预期之中）；还没有真实 LLM 请求。
- 决策：holdout 用文件隔离（`data/sealed/`）；单次实验便宜时两个候选都跑；新增 `sentinel_to_missing` 特征动作。

### 2026-11-14 00:55–01:13 · 夜间无人值守代理（Luna805 发起）
- 做了：确定性引擎（W01–W05、W08），14 个测试；详见 `docs/night-run/STATUS.md`、`DECISIONS.md`、`BLOCKERS.md`（`7108d57`）。
- 问题：API 预算为 0，所以没有接入真实 LLM；数据用的是乳腺癌冒烟数据集。

