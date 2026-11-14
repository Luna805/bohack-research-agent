# 开发日志 · D · 展示与材料

### 2026-11-14 约 19:50–20:05 · yirran（协调人）+ Claude Code · 左栏按项目分组（分支 `c/workbench-ui`）

- 做了：☰ 抽屉从"研究记录 + 按日期分组"改成"项目"目录树（参考 Claude Code）：每个任务一个可折叠文件夹（内置 Bank / Adult，以及每个已注册的上传 CSV），下面挂这个任务的每次研究，一行显示"来源 · 分数"和开始时间（今天 `HH:MM`，更早"昨天"/"11月13日"），运行中带转圈图标；当前研究高亮、所在项目加粗；项目右侧 `+` 在该项目里新建研究（内置任务走示例确认流程，上传任务复用已确认的协议）；有研究的项目按最近一次排在前面，没跑过的内置任务也列出来；搜索同时匹配项目名、系统、来源和编号。已下线任务（Breast Cancer）的旧 run 仍按项目显示，但没有 `+`。新增 `workbench.project_groups` / `when_text` 及测试。
- 验证：全量 pytest 102 passed；ruff 通过；浏览器里在 8594 走通：展开/折叠、打开 run（高亮）、`+` 新建 Adult 研究、搜索 "llm" 只剩 Bank 的 LLM run。

### 2026-11-14 约 19:40 · yirran（协调人）+ Claude Code · 工作台布局（分支 `c/workbench-ui`）

- 做了：按协调人确认的设计稿（画布 “BudgetLab 工作台重构原型”）把研究页改成“左对话、右工作区”：☰ 打开研究记录抽屉；工作区四个标签（文件 / 查看器 / 研究路径 / 得分曲线），运行中默认打开研究路径；右下角实验面板（实验 / Token / 验证）；浅色主题。先合并了 `d-ui` 的 0369f63（分岔图按模型命名、图例弹窗），分岔图配色改成浅色主题可读的颜色。新增 `budgetlab/ui/workbench.py`（文件列表限定在 run 目录内、本轮新文件、实验表、研究进度、研究记录），测试 `tests/test_ui_workbench.py`。
- 验证：全量 pytest、ruff；本地浏览器走通空状态 → 示例 → 确认方案 → 脚本化 Bank 和 Breast Cancer 运行 → 运行中刷新 → 自动切到完成 → 快捷问题和文件 chip → 查看器 / 研究路径 / 得分曲线 → 研究记录抽屉 → 系统对比 → 上传 CSV 示例。
- 问题：LLM 追问这次没在页面里实测（本机 worktree 没有 .env），逻辑沿用 main。研究结束那一刻 2 秒刷新的块可能还有一次在途，所以结束时会多重跑一次页面。

### 2026-11-14 · D + Codex · 对话与证据工作区调整

- 做了：历史研究改为用户与助手消息；右栏可展开预览协议、契约、事件、预算、汇总、报告和近期实验文件，运行中自动刷新；分岔节点用模型和特征调整说明；颜色收敛为深色、浅色和荧光绿，保留缓慢极光与减少动态效果设置。
- 验证：`ruff check budgetlab/ui tests/test_ui_insights.py`、`pytest -q tests/test_ui_insights.py tests/test_ui_presentation.py`（7 passed）；Streamlit AppTest 首页、历史研究、证据文件和对比页无异常。
- 问题：当前执行环境无法完成浏览器视觉截图；`main` 上的新协议和问答功能仍待与 `d-ui` 合并。
- 下一步：合并 `main` 后保留其新功能，再做完整回归和浏览器视觉检查。

### 2026-11-14 19:48（北京时间） · Codex · 提交前验证与文档脚本格式整理

- 做了：按用户要求整理当前页面、研究路线说明、自动最终测试流程、测试和技术说明文档，准备提交并推送到 `d/remove-protocol-confirmation`。修正文档生成脚本 `tools/build_technical_document.py` 的导入、语句格式和长行问题；通过语法树比对确认格式处理未改变逻辑或文档文字。
- 验证：全量 `pytest -q` 为 120 passed（371.48 秒）；最新 UI 与快捷问答相关测试为 40 passed；`ruff check .`、`ruff format --check budgetlab tests`、`git diff --cached --check` 通过。`uv sync --frozen --extra dev --extra llm --extra ui --dry-run` 确认锁定依赖无需变更。
- 问题：文档 QA 中间 PDF 与渲染截图保留本地，不纳入本次提交；没有调用真实 LLM，也没有执行现有研究记录的最终评测。
- 下一步：完成当前分支推送，供团队审阅与后续合并。

### 2026-11-14 · Codex · 用方案名称和入选原因解释研究路径

- 做了：将图中 `r01-c1` 等内部编号替换为“第1轮·方案1”，自动搜索按实际搜索顺序命名；图上显示开发分数，节点详情显示模型名称、对照方案及基于保存证据的入选原因。合格但未入选的分支标为“已改善·未选”，详细区解释评分低于优先复核方案、同分时耗时排序或复核未通过；资料不足时不猜原因。最终方案用绿色实心菱形，上游对照步骤用空心圆，明确绿色路径不是多个最终模型；执行路线的动态高亮保留。技术编号和原始假设移入折叠详情，同步侧栏分数图和当前任务结论的方案名称。
- 验证：UI 与快捷问答相关 pytest 40 passed（新增 7 项名称、未入选原因、同分、复核失败和动态状态等检查）；Streamlit AppTest 核对历史记录下拉名称、实际未入选原因、技术编号保留与得分图名称对应。浏览器核对第1轮方案2显示开发分数 0.6931，低于最终方案 0.7096，并检查窄屏分支标签，缩短图内文案以消除重叠。`ruff check budgetlab tests`、修改文件格式检查、`git diff --check` 通过。
- 问题：无新增问题；没有更改研究排序、训练、复核或最终评测规则，也没有运行真实实验或读取封存测试数据。
- 下一步：供用户检查改进后的表述；改动仅在本地，未提交或推送。

### 2026-11-14 · Codex · 将最终测试并入页面后台流程

- 做了：根据用户对独立 holdout 按钮的反馈，把新页面任务改为“研究完成并确定模型 → 独立测试集上的一次最终测试 → 展示结果”，由新增 `budgetlab/ui/research_job.py` 在同一后台进程顺序调用现有研究与评测接口。研究引擎、CLI、评测模块和数据隔离规则未改动；真实分数仍由现有评测模块产生。页面用“最终测试”解释用途，正常新任务不再需要单独按钮；历史未测记录仅提供折叠的补测入口，失败显示原因和明确重试。刷新只读取结果，不触发评测；后台状态写入 `ui_final_test.json` 并追加账本事件。同步右栏、证据文件名称和 README。
- 验证：UI 与快捷问答相关 pytest 33 passed（新增 8 项后台流程测试，覆盖先研究后测试、研究失败不评测、保存结果复用、失败状态、显式重试、账本事件序号和入口参数）；Streamlit AppTest 检查进行中／失败／完成状态与后台启动命令，全部通过；`ruff check budgetlab tests` 通过。浏览器确认历史页面使用“最终测试”说明和折叠补测入口，旧按钮已消失。
- 问题：本次使用模拟研究／评测依赖验证流程，没有启动真实研究、读取封存测试数据、消耗已有记录的一次测试机会或调用真实 LLM。
- 下一步：新启动的页面任务会自动完成最终测试；本地改动尚未提交或推送。

### 2026-11-14 · Codex · 研究路线动态高亮

- 做了：研究路径按账本中的开始／完成／失败事件高亮当前节点及完整上游路线（蓝色），切换实验时撤销旧支路高亮；未产生结果文件的进行中实验也立即显示，分数保持未知。提案／审查从已保存上下文读取当前路线，标定和基线复核指向基线，候选复核和最终拟合按原始规格匹配路线。已结束研究显示绿色最终采用路线，已知进程退出或终止事件清除执行高亮。按运行编号隔离图表状态，沿用每 2 秒刷新；修复实时实验按文件名排序导致父子分离的问题，保留所有兄弟分支和节点说明。
- 验证：UI 和快捷问答相关 pytest 25 passed（新增 9 项针对切换、失败、未完成节点、复核、历史父子顺序等行为的测试）；`ruff check budgetlab tests`、修改文件格式检查通过。Streamlit AppTest 验证主页面历史记录和三个回放阶段；浏览器用真实保存事件的隔离回放验证 r01-c1 → r01-c2 → 研究完成，确认旧支路变灰、新路线变蓝、完成后最终路线变绿。主前端已显示更新后的历史研究路径。没有启动新训练或调用真实 LLM；回放文件在忽略目录 `ui_state/branch-preview/`。
- 问题：无新增问题；原有未跟踪 tools 脚本的 lint 问题未涉及。
- 下一步：供用户在下一次真实研究中体验；改动仅保存在本地，尚未提交或推送。

### 2026-11-14 · Codex · 移除开跑前的重复确认

- 做了：按用户要求，在 `d/remove-protocol-confirmation` 删除研究方案展示区的“我确认目标列、预测时点，以及哪些数据列可以用来预测”复选框及其状态依赖；示例任务直接采用已有任务说明，准备数据和开始研究不再需要先勾选。保留目标、时点、字段规则展示、数据就绪检查和已有研究防重复启动；已注册 CSV 不再二次确认，首次上传协议编辑流程不变。同步 README 和页面提示。
- 验证：UI 与快捷问答相关 pytest 共 16 passed；Streamlit AppTest 检查数据已准备、未准备、研究运行中、旧会话残留未确认状态四种情况均通过；`ruff check budgetlab tests`、`ruff format --check budgetlab/ui/app.py`、`git diff --check` 通过。浏览器刷新后确认复选框消失，Bank 示例的“开始研究”按钮可用，未启动新研究或调用真实 LLM。
- 问题：`ruff check .` 在本来就存在的未跟踪 `tools/build_technical_document.py` 中报 79 项问题，本次未修改该脚本。
- 下一步：由用户体验新的启动流程；改动仅在本地，未提交或推送。

### 2026-11-14 约 18:30 · yirran（协调人）+ Claude Code · 把 `d-ui`（3e2bae8）合进 `main`
- 做了：三栏布局、深色主题、研究路径分岔图、左侧 Token 面板和六阶段进度、右侧验证结果全部采用 D 的版本；`d-ui` 分支没有的 main 改动按 main 保留：LLM 开关（移到左侧研究目录）、协议 Agent 起草、开放问答、页面措辞（研究方案、数据列能否用来预测、快捷问题胶囊）、holdout 95% 区间，以及回答下的“相关文件”链接和只读查看页。Token 面板的说明改成：只统计本次研究的提案和审查，CSV 协议起草和开放问答另记在 `ui_state/`。
- 验证：全量 pytest、ruff；本地浏览器看了首页、已完成 run 的追问和链接、历史 run、系统对比。

### 2026-11-14 · D + Codex · 精简研究工作区视觉

- 做了：保持三栏、进度、分岔、验证及对话功能不变；改为深色工作台与荧光绿/蓝色实验状态，去掉重复的页头说明、运行编号提示和常驻的零 Token 清单，过程明细改为展开查看。
- 验证：`ruff check .`、`ruff format --check budgetlab tests`、UI 聚焦测试及 Streamlit AppTest（首页、历史 run、系统对比）。
- 问题：无头浏览器在当前 Windows 环境因 GPU 进程失败，仍需人工看实际视觉效果。
- 下一步：按浏览器实际截图微调间距和窄屏布局；对接 A 的协议和问答接口。

### 2026-11-14 · D + Codex · 固定三区与可读的实时研究地图

- 做了：按参考图将顶部与两侧栏固定在视口内，中间研究内容单独滚动，底部任务输入固定；把事件步骤移到左侧六阶段进度，默认收起明细；中间保留协议、实验分岔、结论和快捷追问。地图对进行中与历史未完成 run 每 2 秒刷新，节点悬停显示实验来源、依据、分数和裁决，可按编号查看原始假设。
- 验证：Streamlit AppTest 检查首页、历史 run、侧栏详情和系统对比均无异常；`python -m pytest -q tests/test_ui_insights.py tests/test_ui_presentation.py`（7 passed）。
- 问题：固定布局和窄屏样式还需浏览器视觉验收；历史记录的自由输入仍未接 A 的开放问答 Agent。
- 下一步：视觉验收后同步 `main` 中 A 的接口，再接自由协议和开放问答。

### 2026-11-14 · D + Codex · 三栏研究工作区

- 做了：按参考图调整为黑白灰三栏布局和橙色重点；左侧按任务、系统和状态索引研究记录并显示各过程 Token，中央保留对话并新增真实实验分岔图，右侧显示开发集实验分数、六阶段闭环与验证状态。所有数字读取 `runs/` 证据，脚本化提案明确标成 0 Token；未做的 holdout 显示“尚未评测”。
- 验证：`python -m pytest -q`（64 passed）、`ruff check .`、`ruff format --check budgetlab tests`；Streamlit AppTest 检查首页、已完成 run、研究地图及系统对比，无异常。数据核对使用本地演示 run `20261114T072400Z-budgetlab-21f9e4`，非正式成绩。
- 问题：当前没有可评测的 holdout 记录，故该面板尚未用真实 holdout 分数验收；参考图中与本项目无关的模型参数和示例统计量没有照搬。
- 下一步：用浏览器核对窄屏与实际视觉效果；待正式结果产生后检查最终评测卡。A 的开放式协议与问答 Agent 到位后接入对话入口。

### 2026-11-14 约 16:50–17:20 · yirran（协调人）+ Claude Code，分支 `c/pre-freeze-fixes`（代 D 接 LLM 路径，协调人要求）
- 做了：① 侧边栏加"使用 LLM"开关：`.env` 有 `LLM_MODEL`、`LLM_API_KEY` 且装了 llm 依赖时默认打开，否则灰掉并说明原因（兜底路径不变）。开跑时 `--proposer llm`，配置写到 `ui_state/configs/<task>-llm.yaml`，LLM 预算和设置直接取正式矩阵 `configs/benchmark/final.yaml` 的 overrides（新文件 `budgetlab/ui/llm.py`）。② 上传 CSV：选好目标列和正类后，可以点"让协议 Agent 起草字段可用性"，草稿预填到逐列确认表里，`questions_for_user` 逐条显示；Agent 只看开发数据的画像（C 新增 `development_profile`，和 `prepare_task` 切出的开发集逐行一致），不看 holdout。演示 CSV 同时载入标准答案时，显示 Agent 和标准答案一致几个字段、漏排除了哪些。Token 记到 `ui_state/llm_calls.jsonl`。③ 研究结束后，底部对话框变成"追问"：开放问题交给 A 的问答 Agent，回答下面列出证据引用和逐个数字的核对结果（✅/⚠️），Token 记到 `ui_state/qa_calls.jsonl`，每个会话最多 20 次请求、5 万 Token。④ 研究结束时整页刷新一次，侧边栏会显示"研究已完成"；分数保留 4 位小数；holdout 显示 95% 区间；可用特征下限从 2 改成 1（B 已修引擎）。
- 验证：锁定环境里页面打开；LLM 开关打开时预算卡片显示 `llm`（qwen3.7-plus，最多 60 次请求、300,000 Token）；关掉后脚本化 Bank 全程跑通。新增 `tests/test_ui_llm.py`。**页面里的真实 LLM 调用还没测**（要花钱，等协调人同意）。
- 下一步：D 过一遍页面文案；现场演示前用真实 LLM 走一遍上传 → 起草 → 开跑 → 追问。

### 2026-11-14 · D + Codex · 同步演示数据并核对上传协议

- 做了：在 `d-ui` 合并远端最新 `main`（`9a2ccce`，含 C 的学生预警 CSV）；只对该内置 CSV 增加显式“载入人工标准协议”按钮，仍要求用户核对并确认；步骤卡现在显示每轮两个候选及其假设，并明确标出脚本化提案是 0 Token。
- 验证：Git 经本地代理和 OpenSSL 可读取远端、fetch 和合并；用户 PowerShell 的 `git push --dry-run origin d-ui` 返回 `Everything up-to-date`，远端 `d-ui` 为 `9a2ccce`。AppTest 核对演示协议排除 `G1`、`G2`、`G3`、`absences`，确认后生成上传任务 `upload-deb9e1780d`；脚本化研究 run `20261114T072400Z-budgetlab-21f9e4` 完成且为 `confirmed_pass`（本地演示，非成绩）。最终 `python -m pytest -q` 为 61 passed；历史 run 页面显示提案卡且无异常；`ruff check .` 与 `ruff format --check budgetlab tests` 通过。
- 问题：受限执行环境里的 `git push --dry-run` 因凭据管理器无法保存凭据而失败；用户 PowerShell 的 dry-run 已验证推送通道。
- 下一步：核对研究 run 及全量回归；由用户审核 D 改动后，再提交并推送开发分支。

### 2026-11-14 · D + Codex · 合流后接入上传与第二示例

- 做了：`d-ui` 离线合并本机 `main`（`6b39e75`）；从 Desktop stash 仅恢复 D 的文件；页面接入 Adult 示例、CSV 人工确认协议、C 的注册与准备接口，优化零 Token 曲线、步骤卡及历史 run 的结论和快捷问答；更新 README 与运行产物忽略规则。没有修改协调人的 `docs/INTERFACES.md`。
- 验证：`python -m pytest -q`（59 passed）、`ruff check .`、`ruff format --check budgetlab tests`；Streamlit agent API 的首页和开发数据对比页无异常；AppTest 的多特征 CSV 能生成任务配置，历史 run 显示结论与 3 个快捷问题且无异常。脚本化上传任务 `20261114T061017Z-budgetlab-3a8e2c` 跑通，开发集基线 1.0（仅为构造的验收数据，不是成绩）。
- 问题：单可用特征 CSV 在引擎的工具搜索阶段触发“删掉所有特征”异常，页面已提前提示并禁止启动，需 B 修引擎。电脑仍无法连接 `github.com:443`，本地 Git 暂不能 fetch/push；Adult 首次下载也因网络权限失败，离线 Breast Cancer 数据准备成功。远端 `main` 已比本机多两个 C 的提交。
- 下一步：B 修复单特征边界；A 提供协议与开放问答 Agent 后接入；网络恢复后同步远端 `main`、复测并走 PR。

### 2026-11-14 · D + Codex · 步骤卡可读性

- 做了：步骤卡直接显示实验模型、开发集分数、候选编号和裁决；原始事件保留在“显示全部事件”中，证据文件路径仍可见。
- 验证：`python -m pytest -q tests/test_ui_presentation.py`（3 passed）、`ruff check budgetlab/ui`、`ruff format --check budgetlab/ui`，Streamlit AppTest 首页无异常。此前全量测试 38 passed；本次修改后尚待重新跑全量测试。
- 问题：当前会话不能写 `.git/FETCH_HEAD`，分支仍在 `40cb6f5` 之后，C 的 CSV 接口与 Adult 示例尚未进入本地工作树。
- 下一步：快进 `origin/main` 后接入 CSV 和 Adult，完成真实页面验收。

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

- 新增 Streamlit 对话式研究页：任务说明确认、示例数据准备、脚本化研究启动、事件步骤卡、结果、一次性 holdout 按钮和 0 Token 快捷问答。
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
