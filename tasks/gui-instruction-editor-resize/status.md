Status: completed

Current Findings:
- `ReviewPage` 的两个任务说明输入框当前用了固定较高的 `QPlainTextEdit`。
- 现状默认高度偏高，压缩了页面可视区域。

Next:
- none

Passed Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- screenshot:
  - `data/output/gui-instruction-editor-resize.png`

Blockers:
- none
