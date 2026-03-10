Status: completed

Current Findings:
- `ReviewPage` 左侧总高度超过可用区域时，没有滚动容器承接溢出。
- `SettingsPage` 内容区域同样没有滚动容器承接溢出。
- `QFormLayout` 中关键控件在默认窗口下被压缩到约 10px 高度。
- `SettingsPage` 中工具链与默认行为表单控件在默认窗口下被压缩到约 25px 高度。
- 修复后：
  - `backend_combo`: 40px
  - `model_edit`: 40px
  - `progress_combo`: 40px
  - `output_dir_edit`: 40px
  - `timeout_spin`: 40px
  - `effort_combo`: 40px
  - `SettingsPage.default_backend`: 40px
  - `SettingsPage.default_model`: 40px
  - `SettingsPage.default_progress`: 40px
  - `SettingsPage.default_timeout`: 40px
  - `SettingsPage.default_effort`: 40px
  - `SettingsPage.output_dir`: 40px
  - `SettingsPage.claude_bin`: 40px
  - `SettingsPage.opencode_bin`: 40px
  - `SettingsPage.opencode_provider`: 40px
  - `SettingsPage.opencode_api_url`: 40px
  - `SettingsPage.opencode_api_key`: 40px

Next:
- none

Passed Validation:
- 根因采样脚本已确认问题存在。
- `uv run python -m app.main --help`
- `uv run pytest -q`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-config-before-fix.png"`
- review page screenshot:
  - `data/output/gui-config-after-fix.png`
- settings page screenshot:
  - `data/output/gui-settings-after-fix.png`

Blockers:
- none
