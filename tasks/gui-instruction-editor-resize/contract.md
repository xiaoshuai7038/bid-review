[Task Spec / Success Contract]

Goal:
- 优化“新建审查任务”页面中“任务补充说明”的两个输入框高度。

Desired Effect:
- 默认高度比现在更低，不占用过多版面。
- 当用户输入内容变多时，输入框能自动长高。
- 超过合理上限后保留内部滚动，不无限拉长页面。

Non-goals:
- 不修改输入内容本身的传递逻辑。
- 不修改设置页中的默认补充指令文本框。
- 不改右侧日志/状态区域布局。

Deliverables:
- 自适应高度文本编辑控件或等价实现。
- ReviewPage 中两个说明输入框接入。
- 回归测试与截图验证。

Done When:
- 默认高度低于当前实现。
- 输入多行文本后高度会自动增加。
- 到达上限后不再继续拉高。
- 验证通过。

Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-instruction-editor-resize.png"`

Review Gates:
- 仅修改 GUI 与测试文件，不改 CLI/后端协议。

