# 开发日志 · C · 实验与评测

新的写在最上面。每条包含：时间、谁（人或代理）、做了什么、怎么验证的（命令或 run_id）、遇到的问题、下一步。

<!-- 示例
### 2026-11-14 13:00 · 姓名 + 代理
- 做了：…（提交 abc1234）
- 验证：pytest 通过；run 20261114T…
- 问题：…
- 下一步：…
-->

### 2026-11-14 约 15:35–15:50 · yirran（协调人）+ Claude Code
- 做了：拉取并检查队友的分支。B 的 `b/engine-stability` 合入 main（`bf4cc72`，CI 通过）；A 的 `a/agent` 合入 main（真实 LLM `qwen3.7-plus`、协议 Agent、`extra_body`）。`configs/benchmark/final.yaml` 改用 A 验证过的设置（tool 模式、单次输出上限 3000、`extra_body: {enable_thinking: false}`、每个 run 60 次请求和 30 万 Token），并按 A 实测的单个 LLM run 约 15 分钟更新了耗时估算：3 次重复串行约 3.3–3.8 小时，可以按任务拆成两个进程并行。HANDOFF 待办表已同步。
- 验证：main、A、B 模拟合并后，锁定环境 75 passed，ruff 通过；A 分支的 CI 通过。这台 Mac 上没有 `.env`，所以 `final.yaml` 的开跑前检查如实报"没有配置 LLM"。
- 问题：①下午这台 Mac 用电池、Docker 虚拟机又占着 CPU，训练慢了 2–5 倍；接上电源后恢复，但 Docker 仍占约 29% CPU，跑正式矩阵前要退出。②本地文件夹被做经验库的会话占用（`b/memory`，改动未提交），协调人的合并都在独立 worktree 里进行。
- 下一步：把 Key 配到正式矩阵用的机器上，在这台机器上先测一个真实 LLM run 的耗时，再定重复次数和是否并行（19:00）。

### 2026-11-14 约 13:40–13:53 · yirran + Claude Code（分支 `c/demo-csv`）
- 做了：演示数据 `examples/student_risk/`，用 UCI Student Performance 的葡语课程数据做"学年初预测期末不及格"：649 人，100 人不及格，CC BY 4.0。CSV **有意保留了 G1、G2、G3**（`build_demo_csv.py` 会下载、校验哈希后重新生成）。`card.yaml` 是标准答案：必须排除 G1、G2、G3，`absences` 是边界情况（统计的是本学年缺勤）。README 写了对话里的一句话描述、给 A 的打分规则和用法。TEAM 和 INTERFACES 8.1 已加上指引。
- 验证：新增离线测试，用标准答案注册后恰好排除这 4 列；`test_csv_task.py` 7 个测试通过；ruff 通过。实跑（scripted，budgetlab，各 1 次）：正确协议的 holdout 是 0.649（0.551–0.745），只排除 G3 时是 0.890，所有字段都可用时是 1.000；每次约 20 秒。协议越错，分数越"好看"，适合现场演示"任务理解"的价值。
- 注意：holdout 只有 130 人，区间很宽；正确协议下开发集和 holdout 的差距（0.722 对 0.649）不能据此判断过拟合。

### 2026-11-14 约 13:17–13:30 · yirran + Claude Code（分支 `c/dev-results-ci`）
- 做了：在干净的 `e053b73`（机器空闲）上重跑两个任务的开发矩阵 → `results/dev-20261114T051756Z`（scripted，1 次重复，6 个 slot 全部成功），这是第一份带 holdout 置信区间和配对 bootstrap 的结果，交给 D 当样例数据。
- 结果：

  | 任务 | 系统 | holdout（95% 区间） | 相对随机搜索 Δ（配对 95% 区间） |
  |---|---|---|---|
  | Bank | random_search | 0.7099（0.696–0.725） | — |
  | Bank | budgetlab_no_schedule | 0.7099（0.696–0.725） | 0（预测完全相同） |
  | Bank | budgetlab | 0.7099（0.696–0.725） | 0（预测完全相同） |
  | Adult | random_search | 0.8143（0.805–0.823） | — |
  | Adult | budgetlab_no_schedule | 0.7941（0.785–0.803） | −0.0202（−0.029 至 −0.011，**完全低于 0**） |
  | Adult | budgetlab | 0.8151（0.805–0.824） | +0.0008（−0.004 至 +0.005，区分不开） |

- 解读（仍然是 scripted，不是成绩）：在 Adult 上，脚本化提案器单独使用时明显比随机搜索差，配对区间完全在 0 以下；加上规则调度后追平随机搜索。配对 bootstrap 能把"真的有差别"和"区分不开"分开，这正是正式矩阵需要的。

### 2026-11-14 约 12:55–13:15 · yirran + Claude Code（分支 `c/holdout-ci`）
- 做了：holdout 置信区间和配对检验。`evaluation/` 在唯一一次评测时：用 bootstrap（1000 次，固定种子）算出 95% 区间 `holdout_ci95`；保存不含标签的逐行预测 `holdout_predictions.csv`（标签只留在 `data/sealed/`）。新增 `paired_bootstrap()`：两个交付模型在同一批重采样行上打分后相减。矩阵跑完后对每对"系统 vs 随机搜索"做配对 bootstrap，写入 `paired_bootstrap.json`，并在 `comparison.json` 和 `aggregate.md` 里报"区间完全在 0 以上 / 以下"的配对数；`aggregate.csv` 末尾新增 `holdout_ci_low` 和 `holdout_ci_high` 两列。指标计算改为基于混淆矩阵的向量化版本，有测试保证和训练时的 sklearn 定义一致。
- 验证：新增 `tests/test_holdout_ci.py`（指标一致性、区间可复现且包含点估计、roc_auc）；`test_benchmark.py` 检查区间、预测文件不含标签、配对区间；锁定环境全套 55 passed；ruff 通过。在机器空闲时用 Bank 实跑一个小矩阵（临时目录，代码未提交）：三个系统交付的模型预测完全相同（holdout 都是 0.7099），单个分数的 95% 区间是 **0.696–0.725**，配对差值为 0、区间 [0, 0]，判为 identical。
- 结论：Bank 上单个 holdout 分数的不确定性约 ±0.015，这正是限制说明里"几个千分点的差异不算数"的依据。LIMITATIONS 和 INTERFACES（1.2、5）已同步。
- 注意：在此之前评测过的 run 没有预测文件，无法补算区间，因为补算需要再看一次 holdout，违反"只评一次"的规则。已提交的 `results/dev-20261114T030336Z` 里没有区间；需要的话可以重跑一次开发矩阵。

### 2026-11-14 约 12:43–12:48 · yirran + Claude Code（分支 `c/report-tables`）
- 做了：数据与评测限制说明初稿 `docs/LIMITATIONS.md`。第 0 节是可以直接做成 PPT 的一页版；第 1–3 节分别是数据与任务、评测方法、系统与工程的限制（例如：只有两个任务、随机分层切分偏乐观、公开数据集可能被 LLM 记住、holdout 只有一份、工程门槛不是显著性检验、只重复 3 次、只用一个 LLM、对照组按实验数而不是时间对齐、文件级隔离不是沙箱）；第 4 节列出可以说和不要说的表述；第 5 节留给正式成绩出来后补；第 6 节是可以补强的地方（holdout 的 bootstrap 置信区间、Bank 按时间切分的检验）。
- 验证：文中的数字都对照过配置和数据（holdout 行数、正例率、标定和确认的种子数、随机搜索的 18 次上限、单线程）。
- 下一步：交给 D；等 A 和 D 回复后做演示 CSV。

### 2026-11-14 约 12:33–12:42 · yirran + Claude Code（分支 `c/report-tables`）
- 做了：成绩表新增两部分（`comparison.json` 和 `aggregate.md` 的两个新小节）。一是和参照系统（默认 random_search）的配对比较：同一任务、同一次重复的两个 run 比 holdout，胜/平/负的界线是两者校准 `min_effect` 中较大的那个，另外报 Token、墙钟、实验数的差值和"每 1000 Token 带来的 holdout 差"。二是成本效率：开发集相对基线的提升、每 1000 Token 的提升、每分钟的提升。`aggregate.csv` 末尾新增 `min_effect` 列；矩阵配置可以用 `reference_system` 更换参照系统。用新格式重新生成了已提交的 `results/dev-20261114T030336Z` 的汇总文件（原始运行证据没变）。HANDOFF 进度表同步更新。
- 验证：`test_benchmark.py` 9 个测试通过（新增胜/平/负、未配对 run、出错 run、不花 Token 时效率为空的测试）；ruff 通过。
- 说明：基线不在 holdout 上评测，所以"相对基线的提升"只能用开发集分数；系统之间的 holdout 比较用配对表。

### 2026-11-14 约 11:55–12:00 · yirran + Claude Code（分支 `c/final-prep`，基于 `c/second-task`）
- 做了：矩阵脚本增加 **LLM 开跑前检查** `preflight()`：`proposer: llm` 时检查每个任务的 LLM 预算是否为正、模型名和 Key 是否已配置（不发请求）；不通过就在创建 results 目录之前报错，`--dry-run` 也会输出检查结果。起草 `configs/benchmark/final.yaml`（LLM，Bank 加 Adult，三个系统，3 次重复，每个 run 的 LLM 预算为 40 次请求、30 万 Token，`max_output_tokens` 2000，待 A 确认）和备用的 `configs/benchmark/final-scripted.yaml`。
- 耗时估算（按机器空闲时的实测）：scripted 每次重复约 11.5 分钟（Bank 248 s + Adult 444 s），3 次重复约 35 分钟；LLM 版每次重复预计 20–35 分钟，3 次重复约 60–100 分钟，20:00–00:30 的窗口足够。如果 A 在 19:00 测得单次提案少于 10 秒，可以改成 5 次重复。
- 验证：`test_benchmark.py` 8 个测试通过（新增开跑前检查的测试）；锁定环境全套 50 passed；ruff 通过；在本机对 `final.yaml` 做 dry-run，检查正确地报出"没有配置 LLM"，`final-scripted.yaml` 显示 ok。`c/second-task` 的 CI（`c71a56f`）通过。
- 待决定：正式矩阵用哪个 LLM、预算多少（A 和协调人）；重复 3 次还是 5 次（19:00 定）。

### 2026-11-14 约 11:38–11:55 · yirran + Claude Code（分支 `c/second-task`）
- 做了：第二个任务 **UCI Adult**（根据人口普查记录判断年收入是否超过 5 万美元；共 48,842 行，正例 24%）。适配器会自动下载并校验 `adult.data` 和 `adult.test` 的哈希，把两个文件合并后由我们自己重新切分（开发集 39,073 行，holdout 9,769 行），并把 `?` 转成缺失值。场景卡标注了 `fnlwgt`（抽样权重，不描述个人）、`education-num`（和 `education` 是同一信息），并在限制里写明 `race` 和 `sex` 是受保护属性。新增 `configs/adult.yaml`；`configs/benchmark/dev.yaml` 改为包含两个任务。
- 验证：`tests/test_tasks.py` 3 个离线测试通过（场景卡覆盖所有列、读文件和标签清洗、未知标签拒绝）；锁定环境全套 49 passed；ruff 通过。
- Adult 小矩阵（scripted，1 次重复，未提交代码 `0ce4c7c-dirty`，结果放在临时目录、不入库；机器空闲时运行）：

  | 系统 | 交付 | 开发最优 | holdout | 实验数 | 墙钟 |
  |---|---|---|---|---|---|
  | random_search | random-10 | 0.8154 | 0.8143 | 18 | 163.5 s |
  | budgetlab_no_schedule | r03-c1 | 0.7971 | 0.7941 | 6 | 135.4 s |
  | budgetlab | tool-02 | 0.8147 | 0.8151 | 8 | 145.3 s |

  基线是 0.7792，三个系统都 confirmed_pass。观察：脚本化提案器的规则是照着 Bank 写的，在 Adult 上 4 个假设都没达到门槛；完整版靠规则触发的随机搜索找到了 HGB 方案，比 no_schedule 高约 0.02。这只是单次运行，**不是结论**，但说明"提案器弱的时候调度能兜底"，也说明提案需要真正理解数据——这正是真实 LLM 应该体现价值的地方。
- 下一步：为 20:00 的正式矩阵做准备（LLM 开跑前检查、final 配置、耗时估算）。

### 2026-11-14 约 11:15–11:35 · yirran + Claude Code（分支 `c/csv-task`）
- 做了：通用 CSV 适配器 `budgetlab/tasks/csv_task.py`。`read_csv_any` 自动识别编码和分隔符；`validate_csv_for_task` 和 `register_csv_task` 给出中文拒绝理由，一次性列全；注册结果落盘在 `data/uploads/<task_id>/`；`config_for_upload` 生成研究配置。`tasks/__init__.py` 的 `get_task` 能通过 `register_data_root` 登记的数据根目录找到 `upload-*` 任务，`TaskDefinition` 支持从文件读取场景卡；`data.py` 的 `prepare_task` 和 `load_development` 会自动登记数据根目录。INTERFACES 8.2 已同步。
- 验证：`tests/test_csv_task.py` 6 个测试通过，其中一个是上传 CSV（GBK 编码、分号分隔、含中文列名、一个结果泄漏列和一个 ID 列）后完整跑研究和 holdout；锁定环境全套 46 passed；ruff 通过。
- 真实数据试跑：把 UCI 原始的 `bank-additional-full.csv`（4.1 万行，分号分隔，带引号）当作用户上传，注册耗时 0.2 s，`duration` 按协议被排除；budgetlab（scripted，max_rounds 3）的结果和内置 Bank 任务完全一致：基线 0.6412 → 0.7098，确认通过，holdout 0.7099，用时 62 s。用 `job` 当目标列时被拒绝（"只支持二分类，有 12 个取值"）。
- 下一步：合进 main，交给 D；然后做第二个任务。

### 2026-11-14 约 11:03–11:08 · yirran + Claude Code（分支 `c/benchmark`）
- 做了：在机器空闲时（不跑任何其他任务）重跑 Bank 开发矩阵 → `results/dev-20261114T030336Z`，代码版本为 `165a031`（非 dirty）。上一份受干扰的 `dev-20261114T024955Z` 已经移出仓库，不提交。
- 结果（scripted，1 次重复，仅证明管道可用，不是性能结论）：

  | 系统 | 交付 | holdout | 实验数 | fit | 墙钟 | 停止原因 |
  |---|---|---|---|---|---|---|
  | random_search | random-05 | 0.7099 | 18 | 151 | 96.7 s | experiment_limit |
  | budgetlab_no_schedule | r02-c2 | 0.7099 | 8 | 101 | 68.8 s | no_valid_candidates |
  | budgetlab | r02-c2 | 0.7099 | 12 | 121 | 82.3 s | no_valid_candidates |

- 验证：分支 CI（`165a031`）在 Ubuntu 和 Windows 上都通过。
- 下一步：合进 `main`，交给 D 搭页面；然后开始做 CSV 适配器。

### 2026-11-14 约 10:45–11:00 · yirran + Claude Code（分支 `c/benchmark`）
- 做了：对照矩阵脚本 `budgetlab/benchmark.py`（`python -m budgetlab.benchmark`）。按"任务 → 重复 → 系统"串行运行，每个 run 结束后立即做一次 holdout 评测，复制三个结果文件到 `results/<matrix_id>/runs/`，每跑完一个 run 就重写 aggregate.csv/json/md；单个 slot 失败只记一行 error，不中断整个矩阵；支持 `--resume`（任务配置变了会拒绝）、`--dry-run`；`final` 矩阵要求 git 工作区干净。新增 `configs/benchmark/dev.yaml`；INTERFACES 5 增加 aggregate.md、末尾三列（slot_id、status、error）和 5.1 节矩阵配置格式。
- 验证：`tests/test_benchmark.py` 通过（6 个 + 1 个溯源测试）；锁定环境全套 39 passed；ruff 通过。
- Bank 开发矩阵 `results/dev-20261114T024955Z`（scripted，1 次重复）：3 个 slot 全部成功，三个系统都交付同一类方案（带类别权重的随机森林），holdout 均为 0.7099，全部 confirmed_pass。墙钟时间：random_search 203 s、no_schedule 143 s、budgetlab 94 s。
- 问题 1（已修）：这次矩阵的 `code_version` 记成了干净的 `2497875`，但当时 `benchmark.py` 是未跟踪的新文件。原因是 `provenance.git_info` 只检查已跟踪文件的改动。现在改为未被忽略的新文件也算 dirty，但 `results/`、`docs/` 和 `*.md` 不算（它们是输出和文档，不影响行为），并补了测试。**`provenance.py` 是 B 的文件，需要通知 B。**
- 问题 2：这次矩阵运行期间同时在跑测试套件，耗时被干扰，**墙钟时间不能用于对比**。scripted 提案和随机搜索拿到同样的结果是预期之中的，这次只证明管道是通的。
- 下一步：提交分支后，在不跑其他任务的情况下重跑一次开发矩阵（结果会带正确的代码版本），再把那份结果提交给 D 搭页面；本次的 `dev-20261114T024955Z` 不提交。

### 2026-11-14 约 10:35–10:40 · yirran（协调人）+ Claude Code
- 决策：取消单独的"选预设任务 + 开始按钮"表单保底版，直接做对话式研究页。兜底改为在同一个对话页面里走"示例任务场景卡或人逐列确认 + scripted 提案"的路径，并且必须在 16:00 前可用。
- 改动：TEAM.md 4.1–4.4 和时间线（16:00 验收两条路径）；INTERFACES 8.1 的 `DraftProtocol` 增加 `source` 字段；HANDOFF 待办第 5、5b、7、9 项的截止时间提前到 16:00。

### 2026-11-14 约 10:30–10:35 · yirran（协调人）+ Claude Code
- 做了：把「对话式研究页」写进分工文档：TEAM.md 新增第 4 节（流程、三个阶段、约束、验收标准），A、C、D 的任务和文件归属随之更新；INTERFACES.md 新增第 8 节（`DraftProtocol`、通用 CSV 任务、后台运行与步骤卡片的事件对应、证据工具与 `QAAnswer`）；HANDOFF 待办表新增第 5b、7、8、9 项。
- 验证：只改了文档，没有改代码；CI 在 `ffd201b` 上两个平台都是绿的。
- 下一步：各角色认领；D 先做保底版，16:00 验收。
