[Task Spec / Success Contract]

Goal:
- 将设置页中的 `Claude CLI 路径` 改为 Claude 区域下默认折叠的高级可选项。

Desired Effect:
- 普通用户默认看不到 `Claude CLI 路径`。
- 需要时可以展开高级区并编辑该字段。
- 不移除该能力，不影响已保存值。

Non-goals:
- 不删除 `claude_bin` 配置能力。
- 不修改 Claude SDK 调用协议。
- 不调整 OpenCode 配置区结构。

Deliverables:
- 设置页 Claude 高级折叠区。
- 对应测试与截图验证。

Done When:
- Claude 区域默认不直接显示 `Claude CLI 路径`。
- 展开高级区后可正常显示和编辑该字段。
- 验证通过。

Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-claude-cli-collapsed.png"`

Review Gates:
- 仅修改 `app/gui/` 与测试文件。

