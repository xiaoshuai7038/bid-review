Status: completed

Current Findings:
- ReviewPage 和 SettingsPage 当前直接展示 `agent/basic/normal/detailed/events/raw`。
- 这些词对专职写标书的用户不友好。

Next:
- none

Passed Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- screenshot:
  - `data/output/gui-progress-level-labels.png`

Blockers:
- none
