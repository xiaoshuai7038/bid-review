Status: completed

Current Findings:
- Claude 区域仍直接展示 `Claude CLI 路径`，与“默认低频不展示”的需求不一致。

Next:
- none

Passed Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- screenshot:
  - `data/output/gui-claude-cli-collapsed.png`

Blockers:
- none
