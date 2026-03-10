[Task Spec / Success Contract]

Goal:
- 将“新建审查”和“设置”页面中的进度级别选项改成非技术用户易懂的中文描述。

Desired Effect:
- 用户在界面中看到的是通俗中文，而不是 `agent/basic/normal/detailed/events/raw` 这类专业名词。
- GUI 内部仍然保持原始值映射，不影响后端参数传递。

Non-goals:
- 不修改 CLI 参数契约。
- 不修改后端实际接受的 `progress-level` 枚举值。
- 不调整其它无关表单项的文案。

Deliverables:
- ReviewPage 和 SettingsPage 的进度级别中文显示。
- 内部值映射逻辑。
- 回归测试与截图验证。

Done When:
- 两个页面中进度级别都显示中文。
- 读取和保存时仍使用原始内部值。
- 验证通过。

Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-progress-level-labels.png"`

Review Gates:
- 仅修改 GUI 层与测试文件，不改后端协议。

