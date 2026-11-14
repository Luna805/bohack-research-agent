# E 开发日志

## 2026-11-14 · Codex · 功能说明文档

- 完成：扩写 `docs/TOKEN_MANAGEMENT.md`，说明任务路由规则、研究与页面配置、预算结算、审计字段和启用前验证。
- 验证：对照 `budgetlab/token_management.py`、`budgetlab/ui/llm.py` 与现有测试检查描述；`git diff --check`。
- 问题：本地 DeepSeek 端点尚未提供，真实兼容性与节省比例不能在文档中确认。
- 下一步：实际部署端点就绪后执行 `probe-llm` 并补充实测结果。

## 2026-11-14 · Codex · Token 管理

- 完成：新增任务驱动模型路由。Proposer 根据停滞和无效候选选择本地或强模型；强模型不可用或预估超出剩余预算时回退本地。Critic 使用本地模型。协议草拟与问答在页面按任务选择档位；问答调用前检查会话 Token／请求预算。路由原因和实际模型随原有计量调用进入账本。
- 验证：`pytest -q` 109 passed；`ruff check .`、`ruff format --check budgetlab tests`、`git diff --check` 通过。端到端假模型测试确认预留 Token 和路由信息写入调用账本。未发真实 LLM 请求。
- 问题：公司本地 DeepSeek 的工具输出和 usage 尚未通过实际端点验证。
- 下一步：用授权的本地端点执行 `probe-llm`，再做本地／强模型／调度三组对照。
