# 开发日志 · C · 实验与评测

新的写在最上面。每条包含：时间、谁（人或代理）、做了什么、怎么验证的（命令或 run_id）、遇到的问题、下一步。

<!-- 示例
### 2026-11-14 13:00 · 姓名 + 代理
- 做了：…（提交 abc1234）
- 验证：pytest 通过；run 20261114T…
- 问题：…
- 下一步：…
-->

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
