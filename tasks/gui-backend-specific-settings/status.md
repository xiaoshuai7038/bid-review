Status: completed

Current Findings:
- 设置页当前把 Claude 与 OpenCode 配置混在一个表单中。
- `default_model` 是通用字段，不能完整表达两个后端各自的默认模型。

Next:
- none

Passed Validation:
- 代码阅读已确认变更可限制在 GUI 层和本地 settings 层。
- `uv run python -m app.main --help`
- `uv run pytest -q`
- screenshots:
  - `data/output/gui-backend-specific-settings-claude.png`
  - `data/output/gui-backend-specific-settings-opencode.png`

Blockers:
- none
