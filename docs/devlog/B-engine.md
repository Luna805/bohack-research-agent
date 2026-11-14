# 开发日志 · B · 研究引擎

新的写在最上面。每条包含：时间、谁（人或代理）、做了什么、怎么验证的（命令或 run_id）、遇到的问题、下一步。

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
