[Task Spec / Success Contract]

Goal:
- 将桌面端“设置 > 工具链与默认行为”改为按默认后端分离 Claude / OpenCode 配置项。

Desired Effect:
- 通用配置与后端专属配置分开显示。
- 当默认后端选择 `claude` 时，只显示 Claude 相关配置。
- 当默认后端选择 `opencode` 时，只显示 OpenCode 相关配置。
- Claude 与 OpenCode 各自保留自己的默认模型，不再共用一个字段。

Context:
- 当前设置页把 Claude 与 OpenCode 的配置项混在一个表单里。
- 当前 `default_model` 仍是通用字段，不利于两个后端保留各自默认模型。

Non-goals:
- 不修改 CLI 参数契约。
- 不修改 Claude SDK / OpenCode 客户端调用协议。
- 不重做整页视觉风格。

Deliverables:
- 设置页动态 backend-specific 配置切换。
- 设置模型拆分为 Claude / OpenCode 各自默认值。
- 需要时同步更新审查页默认模型加载逻辑。
- 自动化测试与截图验证。

Done When:
- 切换默认后端时，只显示对应后端配置项。
- Claude 与 OpenCode 的默认模型可独立保存与加载。
- 相关验证通过。

Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-backend-specific-settings.png"`

Review Gates:
- 仅修改 `app/gui/`、`app/gui/state/` 与测试文件，不改后端调用协议。

