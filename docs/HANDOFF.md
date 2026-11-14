# BudgetLab 交接说明

> 更新：2026-11-14 09:55（北京时间）· 提交截止 11/15 08:00
> 开发规范见仓库根目录 [`AGENTS.md`](../AGENTS.md)（人和 AI 代理共用，Claude Code 通过 `CLAUDE.md` 自动读取）。

## 0. 先做这几件事

```bash
git pull                                         # 夜间代码在 7108d57，之后的改动见下方开发日志
uv sync --frozen --extra dev --extra llm         # 锁文件新增了 openai 依赖
python -m budgetlab.cli prepare --task bank_marketing   # 下载 UCI 数据，切出密封 holdout（约 1 MB）
python -m pytest -q                              # 应为 17 passed
ruff check .
```

- 如果夜间版本之后你本地又改过 `controller.py`、`tests/conftest.py`，或者改过已删除的 `llm.py`，pull 时会冲突。冲突时以仓库版本为准，把你的改动重新加上去。
- `prepare` 用 urllib 下载，证书优先用 certifi 的（某些 macOS/pyenv 的 Python 缺系统证书）。如果需要代理，先设置 `HTTPS_PROXY`。下载失败时报错信息会给出手动下载的步骤：把 `bank-additional-full.csv` 放到 `data/raw/bank_marketing/bank-additional/` 下即可，程序会校验文件哈希。
- 以上命令已在干净的检出里验证过（uv sync → prepare → 17 passed → ruff 通过）。

## 1. 现在到哪一步了

| 方案工作包 | 状态 | 说明 |
|---|---|---|
| W01 Schema | ✅ | 新增 `SentinelToMissing` 特征动作、HGB 的 `class_weight`、`LoopPolicy`、`CriticAdvice` |
| W02 预算与账本 | ✅ | 新增 `Budget.can_reserve()`（只试算，不改状态）和 `remaining()` |
| W03 数据与隔离 | ✅ | 任务适配器、场景卡、`prepare` 切出密封 holdout、开发集画像 `eda.json` |
| W04/W05 实验与裁决 | ✅ | 夜间版本基础上，随机搜索覆盖了特征动作 |
| W06 LLM 接入 | ⚠️ 代码完成 | Pydantic AI 提案器和 Critic，带预留与结算；只用本地 FunctionModel 测过，**没有真实请求过** |
| W07 主循环 | ✅ | 两个候选、筛查与去重、便宜时都跑、停止规则、工具搜索调度、重规划、方向归因 |
| W08 冻结与最终评测 | ✅ | `evaluate` 每个 run 只能评一次，第二次报错 |
| W09 正式对照矩阵 | ❌ | 还没有批量运行和汇总脚本 |
| W10 展示与材料 | ❌ | 只有 `report.md`，没有 UI 和 PPT |
| P1 经验库 / 自定义特征 / MLE-bench | ❌ | 未开始 |

**实测（Bank Marketing，f1_macro，提案器为脚本化规则，不是 LLM）：**

| 系统 | 基线 | 探索最优 | 确认 | holdout | 实验数 | 耗时 |
|---|---|---|---|---|---|---|
| random_search | 0.641 | 0.710 | confirmed_pass | 0.713 | 18 | 204 s |
| budgetlab（scripted） | 0.641 | 0.710 | confirmed_pass | 0.710 | 14 | 98 s |

最优方案是带 `class_weight=balanced` 的随机森林。脚本化规则本质上也是一种搜索，和随机搜索打平在预期之中；能否拉开差距，要看真实 LLM 的结果。单次 5 折实验 1–10 秒，两个候选都会跑。

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
  reporting.py / cli.py  报告模板；命令行 prepare / research / evaluate / probe-llm / reproduce / replay
configs/bank_marketing.yaml   正式开发配置（预算、循环策略、LLM 设置都在这里）
configs/night_smoke.yaml      乳腺癌数据的快速冒烟配置
```

三个系统：`random_search`（0 Token）、`budgetlab_no_schedule`（消融组：只有提案循环 + 去重 + 预算 + 停止规则）、`budgetlab`（在此基础上加工具搜索调度、重规划和按需 Critic）。

## 3. 开发规范与协作约定

完整规范在 [`AGENTS.md`](../AGENTS.md)，这里只列多人协作最容易出问题的几条：

- **分支**：在 `<名字>/<主题>` 短分支上开发，合并前 `git pull --rebase origin main`；`main` 必须始终能跑演示。
- **CI**：配置文件已写好（Ubuntu + Windows 上跑 lint 和测试），但**还没启用**：yirran 本机的 GitHub token 没有 `workflow` 权限，推送被拒。启用后 CI 是红的不合并。
- **版本可追溯**：每个 run 的 `run_config.json` 自动记录 git 提交号和是否有未提交改动，报告头部也会显示 `code version`。正式结果必须来自无未提交改动（非 dirty）的提交。
- **冻结**：正式矩阵开跑前打 tag `benchmark-freeze`，之后代码和配置不再改动。
- **结果集中**：正式矩阵只在一台机器上跑，精简结果提交到 `results/<run_id>/`；PPT 里的数字只从这里取。
- **认领**：开始做某项待办前，在下表填上负责人并把状态改成"进行中"，然后推送，或者至少在群里说一声。

## 4. 接下来做什么（按优先级）

| # | 任务 | 建议分工 | 负责人 | 状态 | 完成标准 |
|---|---|---|---|---|---|
| 0 | **启用 CI**：给 yirran 的 token 加上 `workflow` 权限后由我们推送；或由仓库所有者在网页上新建 `.github/workflows/ci.yml`（内容向 yirran 要） | 队长 | yirran | 进行中 | Actions 页面里 Ubuntu 和 Windows 两个任务都是绿的 |
| 1 | **确认 LLM 来源**：主办方是否提供模型、Key 和额度，还是自费 | 队长 | – | 等待原文 | 有群公告或手册原文；定下模型名、Base URL、单价 |
| 2 | 真实接口门禁：填 `.env`，配置里设正数的 LLM 预算，跑 `probe-llm` | A | – | 待认领 | Schema 一次通过，usage 有值；tool 模式不行就依次试 `native`、`prompted` |
| 3 | 真实 LLM 跑 Bank：`--system budgetlab --proposer llm` | A | – | 待认领 | 至少 2 轮真实提案→训练→反馈；`llm_calls.jsonl` 的 Token 和 `budget.json` 对得上 |
| 4 | 对照矩阵脚本 `budgetlab/benchmark.py`：系统 × 重复次数，跑完统一 `evaluate`，汇总表格和曲线 | B | – | 待认领 | 默认 3 个系统 × 3 次；输出 CSV/MD 表，以及"最优分—累计 Token""最优分—时间"两张图 |
| 5 | 只读展示页（Streamlit 或静态 HTML），读 `results/` 和 `runs/` | B | – | 待认领 | 三个区域：实时轨迹、性能与成本、证据链；回放模式要有明显标识 |
| 6 | README、PPT、录屏 | 全员 | – | 待认领 | 数字全部来自 `summary.json` / `final_evaluation.json` |
| P1 | 协议理解轨道：给 LLM 不带可用性标注的字段表，让它提出排除列，程序对照场景卡打分 | A | – | 待认领 | 记录首次正确率和成本；这是展示"理解业务约束"最便宜的一步 |
| P1 | `LLMSettings` 支持 `extra_body`（用来关闭思考模式） | A | – | 待认领 | 选定的模型需要时再做 |
| P1 | MLE-bench 两道题的门禁，最多试 1 小时 | B | – | 待认领 | 过不了就放弃，报告里如实说明 |

建议分工：**A（控制器与模型）**负责 `controller.py`、`proposers.py`、`state.py`、`budget.py`；**B（数据、评测与展示）**负责 `tasks/`、`data.py`、`evaluation/`、`search.py`、新增的 `benchmark.py`、`ui/`。

时间检查点：正式矩阵最晚 11/14 20:00 开跑（开跑后冻结代码和配置）；11/15 05:30 后只修阻塞问题。

## 5. 已知问题与限制

- **LLM 来源未确认**：项目里"主办方提供托管模型"的说法来自对群公告的转述，没有原文依据。
- 随机分层切分偏乐观：Bank 数据按时间排序，宏观经济列随时间变化，而本版不做时间切分。这一点场景卡里已经写明，报告也要写。
- `budget.seconds` 统计的是训练子进程时间，不是墙钟时间；墙钟时间看 `summary.wall_seconds`。
- LLM 预留按"估计输入 + 最大输出 ×（重试次数 + 1）"算，比较保守；`max_output_tokens` 默认 3000，非思考模型可以降到 1500–2000。
- 工具搜索的实验 ID（`tool-NN`）按实验总数编号，所以不连续，这是正常的。
- 训练运行在带超时的子进程里，这不是操作系统层面的沙箱，对外不要说成"安全沙箱"。
- `contracts.validate_proposal_batch` 只在测试里用到；主循环的筛查逻辑在 `controller.screen_candidates`。

## 6. 开发日志

新的在最上面。每次工作结束追加一条（格式见 `AGENTS.md`），只写事实和证据。

### 2026-11-14 约 09:45–09:55 · yirran + Claude Code
- 做了：`AGENTS.md` / `CLAUDE.md`、`results/` 目录约定；run 现在会记录 git 提交号、是否 dirty 和环境版本（`budgetlab/provenance.py`）。
- 验证：本地 17 passed，ruff 通过。
- 问题：CI 配置（`.github/workflows/ci.yml`）推送被拒，token 缺少 `workflow` 权限，文件暂时只在 yirran 本地。
- 下一步：启用 CI（见第 4 节第 0 项）；确认 LLM 来源。

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

