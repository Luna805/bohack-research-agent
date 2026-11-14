# 开发日志 · C · 实验与评测

新的写在最上面。每条包含：时间、谁（人或代理）、做了什么、怎么验证的（命令或 run_id）、遇到的问题、下一步。

<!-- 示例
### 2026-11-14 13:00 · 姓名 + 代理
- 做了：…（提交 abc1234）
- 验证：pytest 通过；run 20261114T…
- 问题：…
- 下一步：…
-->

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
