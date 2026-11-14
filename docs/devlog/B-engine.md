# 开发日志 · B · 研究引擎

新的写在最上面。每条包含：时间、谁（人或代理）、做了什么、怎么验证的（命令或 run_id）、遇到的问题、下一步。

### 2026-11-14 约 16:40–17:05 · yirran（协调人）+ Claude Code，分支 `c/pre-freeze-fixes`（代 B 修，协调人要求）
- 做了：① `pyproject.toml` 的 `ui` 加 `pyarrow>=14,<26` 并重新锁定：锁文件里原来是 PyArrow 26.0.1，它要求 NumPy ≥ 2，而我们固定 1.26.4，`uv sync --frozen --extra ui` 装出来的页面一打开就报错（CI 不装 ui，所以没发现）。重锁后只有 pyarrow 一项变化（26.0.1 → 25.0.1）。② `search.SpecSampler._actions`：只有合法列多于 1 个时才提供 drop 动作。原来上传的 CSV 只有 1 个可用特征时，tool search 和 random_search 会把唯一的列删掉，`validate_experiment_spec` 报 `feature actions drop every approved column`，整个 run 崩掉。随机数的消耗顺序没变，Bank、Adult 的采样序列和以前完全一样。
- 验证：干净锁定环境里 `import pyarrow` 正常、页面能打开；新增 `tests/test_search_sampler.py`（去掉修复会失败）；单特征 CSV 端到端跑 budgetlab 和 random_search 都通过。
- 下一步：B 复核一下即可，不需要再改。

### 2026-11-14 · Codex · P0 最终本地验证
- 做了：修正旧 LLM 集成测试夹具，使正常候选只引用真实存在的 `best` 和 `eda`；非法或部分无效证据仍由 `test_engine_loop.py` 独立覆盖。生产逻辑保持“所有 evidence_refs 必须有效”。
- 验证：`python -m uv sync --frozen --extra dev --extra llm` 成功；`python -m uv run --frozen pytest -q` 为 48 passed；`python -m uv run --frozen ruff check budgetlab tests` 和 `python -m uv run --frozen ruff format --check budgetlab tests` 通过。Bank 回归：`20261114T053208Z-random_search-3ab851`（experiment_limit，confirmed_pass，18 个实验）、`20261114T053820Z-budgetlab_no_schedule-e4a74b`（no_valid_candidates，confirmed_pass，8 个实验）、`20261114T054255Z-budgetlab-667a98`（no_valid_candidates，confirmed_pass，12 个实验）。三者均 0 failed experiments、0 LLM requests、0 reserved reservations，预算未超限，最终事件为 run_terminal，冻结模型 SHA256 匹配。
- 问题：工作区存在不属于 B 的未跟踪 `tools/build_technical_document.py`，因此本地全仓 `ruff check .` 会报告该文件的既有问题；分支跟踪文件和 CI 实际检查范围不包含它。新回归因当前工作区含未提交测试和文档，`code_version` 为 `15aa866-dirty`，正式冻结仍需在提交并合入后的 clean commit 上重跑。
- 下一步：提交测试夹具修复，等待 Ubuntu/Windows CI 全绿并合入 main；随后在 clean commit 上执行最终三系统冻结回归。P0 功能本身已通过本地锁定环境验证，暂不开始 P1。

### 2026-11-14 · Codex
- 做了：完成 P0 主循环稳定与接口冻结。收紧候选证据为全部引用必须可用；尾部预算改为按 6 次 confirmation 训练加 1 次最终 refit 的真实实验、fit 和秒数预留；Runner 现在会在启动失败、超时、结果缺失、损坏 JSON 或缺少 fit 计数时结束 reservation，并把无法确认的 fits 记为 unknown；非预期 Runner/Proposer 异常在预算清理后继续抛出，避免掩盖编程错误；运行期异常会写入追加式 run_failed 事件。新增接口产物、循环策略、confirmation 回退、尾部预算、失败终止和 Runner 异常结算测试。
- 验证：python -m pytest -q 通过（40 passed, 4 skipped）；python -m ruff check budgetlab tests 和 python -m ruff format --check budgetlab tests 通过。Bank 回归：20261114T033515Z-random_search-afd737（experiment_limit，confirmed_pass），20261114T034100Z-budgetlab_no_schedule-73d1ed（no_valid_candidates，confirmed_pass），20261114T034505Z-budgetlab-e5c755（no_valid_candidates，confirmed_pass）。三者均无 reserved 账本记录、预算在限额内、冻结模型哈希匹配，且 replay 不修改 budget.json。
- 问题：当前环境没有 uv 或 ruff 可执行文件，因此无法直接运行计划中的 uv sync --frozen --extra dev --extra llm --extra ui 和裸 ruff 命令；使用已安装的 python -m ruff 完成 B 范围检查。全仓 python -m ruff check . 仍被未跟踪的 tools/build_technical_document.py 的 79 项既有 lint 问题阻断，未越权修改。
- 下一步：P0 完成；等待接口使用方确认后再开始任何 P1 工作。

<!-- 示例
### 2026-11-14 13:00 · 姓名 + 代理
- 做了：…（提交 abc1234）
- 验证：pytest 通过；run 20261114T…
- 问题：…
- 下一步：…
-->
