# 开发日志 · D · 展示与材料

### 2026-11-14 · D + Codex · 页面与证据展示

- 做了：新增示例任务入口、运行中步骤卡自动刷新、历史 run 恢复、开发数据对比表与最优分对 Token／时间曲线；开发数据明确标为“开发数据”。
- 验证：此前执行 `python -m pytest -q`（38 passed）、`ruff check .`、`ruff format --check budgetlab tests`，并用 Streamlit AppTest 检查示例入口、任务切换和历史 run 页面。
- 问题：当前会话没有 `.git` 写权限，`git fetch origin` 因无法写入 `.git/FETCH_HEAD` 而失败；本地 `d-ui` 尚未快进到 `5c304ea`。后续页面布局调整尚待重新跑全量检查。
- 下一步：在有 Git 写权限的终端执行 `git fetch origin`、`git merge --ff-only origin/main`，然后重新验证并继续接入 CSV 上传与 Adult 示例。

### 2026-11-14 · D 演示入口与依赖提示

- 新增一键进入示例任务和完成后开始新任务的操作，减少现场演示步骤。
- 对 PyArrow/NumPy 不兼容给出页面内修复命令，避免直接显示 Python 堆栈。
- 验证：AppTest 的示例入口、已完成 run、重置流程均无异常；ruff 检查通过。

### 2026-11-14 · D 自动进度与恢复

- 研究运行时以 Streamlit fragment 每 2 秒刷新步骤卡；快捷问答在刷新后仍保留。
- 侧栏可找回未生成 summary 的 run，避免浏览器刷新后无法查看进行中或中断的证据。
- 验证：全量 pytest 38 passed，ruff 检查和格式检查通过；Streamlit agent API 的首页、历史 run 与全部事件视图均为 ready，服务日志无警告。
- 待办：完整浏览器交互与 C 的真实开发矩阵仍需验收。

### 2026-11-14 · D 页面可读性改进

- 增加已有 run 入口；事件流默认显示各阶段首条与最近事件，可展开全部原始证据。
- 对比页显示来源和“开发数据”标识，给出核心指标表及最优分对 Token／时间曲线；没有结果时明确提示。
- 验证：`ruff check .`、`ruff format --check budgetlab tests`、4 个 D 聚焦测试通过；Streamlit agent API 的首页与历史 run 均为 ready，服务日志无新警告。
- 待办：本分支尚未同步 C 的 `results/dev-*`，因此真实对比数据的页面验收仍待完成；A/C 接口到位后接入自由协议和 CSV。

### 2026-11-14 · D 页面初版

- 新增 Streamlit 对话式研究页：场景卡确认、示例数据准备、脚本化研究启动、事件步骤卡、结果、一次性 holdout 按钮和 0 Token 快捷问答。
- 新增只读证据访问层和快捷问题；读取 `runs/` 产物，不读取 sealed 数据。
- 验证：在本仓库 `.venv` 安装 `.[dev,llm,ui]` 后，`pytest -q` 为 35 passed，`ruff check .` 和 `ruff format --check budgetlab tests` 均通过；Streamlit 服务能正常启动。浏览器内完整研究流程仍待人工验收。
- 下一步：接入 A 的协议/问答 Agent 与 C 的通用 CSV 适配器；在干净环境运行全量 pytest 和页面演示。

新的写在最上面。每条包含：时间、谁（人或代理）、做了什么、怎么验证的（命令或 run_id）、遇到的问题、下一步。

<!-- 示例
### 2026-11-14 13:00 · 姓名 + 代理
- 做了：…（提交 abc1234）
- 验证：pytest 通过；run 20261114T…
- 问题：…
- 下一步：…
-->
