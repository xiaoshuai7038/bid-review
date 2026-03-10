[Task Spec / Success Contract]

Goal:
- 修复桌面端“新建审查任务”和“设置”页面中表单控件被压缩的问题。

Desired Effect:
- 默认窗口尺寸下，审查配置和工具链配置中的输入框、下拉框、数值框能保持正常高度与可读性。
- 当内容总高度超过可用空间时，页面仍可通过滚动保持可操作，而不是继续压缩表单行。

Context:
- 问题发生在 `app/gui/window.py` 的 `ReviewPage` 和 `SettingsPage`。
- 现状是内容总高度超出可用区域后，`QFormLayout` 内字段高度被压缩：
  - `ReviewPage`: 约 10px
  - `SettingsPage`: 约 25px

Non-goals:
- 不修改 CLI 参数契约。
- 不修改右侧运行状态、进度时间线、运行日志的业务行为。
- 不重构整套 GUI 视觉风格。

Deliverables:
- 审查配置区域布局修复。
- 设置页工具链与默认行为区域布局修复。
- 至少一个回归测试，防止表单控件再次被压缩。
- GUI smoke screenshot 验证。

Done When:
- 默认窗口尺寸下，审查配置和设置页工具链表单控件不再被压扁。
- 页面内容溢出时可滚动，而不是压缩表单控件高度。
- 自动化验证覆盖这两处行为。

Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-config-after-fix.png"`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-settings-after-fix.png"`

Review Gates:
- 仅修改 `app/gui/` 与测试文件，不触发 CLI、报告、LLM 调用行为变更。
