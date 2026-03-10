Status: completed

Current Findings:
- `ClaudeClient` 已具备从环境变量读取 Claude SDK base-url/model/auth-token 的能力。
- GUI 设置页缺少 Claude SDK 专项配置入口。
- `默认模型` 已存在，适合作为 `ANTHROPIC_MODEL` 的 GUI 默认值来源。

Next:
- none

Passed Validation:
- 代码阅读已确认可优先在 GUI 层接入，不必改 Claude SDK 客户端协议。
- `uv run python -m app.main --help`
- `uv run pytest -q`
- screenshot:
  - `data/output/gui-claude-sdk-defaults.png`

Blockers:
- none
