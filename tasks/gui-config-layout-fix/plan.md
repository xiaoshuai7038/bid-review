Milestone 1: Root Cause Capture
- Acceptance:
  - 记录当前压缩的根因与受影响控件。
- Validation:
  - 本地几何采样脚本确认表单控件高度异常。

Milestone 2: Layout Fix
- Acceptance:
  - 审查配置区域在默认窗口尺寸下保持正常行高。
  - 设置页工具链区域在默认窗口尺寸下保持正常行高。
  - 内容溢出时可滚动。
- Likely files:
  - `app/gui/window.py`
  - `app/gui/theme.py`
- Risks:
  - 改成滚动区后破坏拖拽区域、按钮布局或整体视觉节奏。

Milestone 3: Regression Coverage
- Acceptance:
  - 测试验证默认窗口下关键表单控件高度不低于安全阈值。
  - review/settings 两页 smoke screenshot 可见修复结果。
- Validation:
  - `uv run python -m app.main --help`
  - `uv run pytest -q`
  - `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-config-after-fix.png"`
