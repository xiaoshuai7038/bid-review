[Task Spec / Success Contract]

Goal:
- 在桌面端“设置 > 工具链与默认行为”中补上 Claude SDK 默认配置入口。

Desired Effect:
- 用户可以在 GUI 中配置 Claude SDK 的 base-url、模型和 auth-token。
- GUI 发起 Claude 审查时，会将这些设置同步到当前进程环境，供现有 Claude SDK 客户端读取。
- 敏感 token 不写入 settings.json。

Context:
- 现有 `ClaudeClient` 已从环境变量读取：
  - `ANTHROPIC_BASE_URL`
  - `ANTHROPIC_MODEL`
  - `ANTHROPIC_AUTH_TOKEN`
- GUI 设置页当前只有通用 `默认模型` 与 OpenCode 配置，没有 Claude SDK 专项配置入口。

Non-goals:
- 不修改 CLI 参数契约。
- 不修改 Claude SDK 请求协议、重试逻辑或报告输出结构。
- 不将 auth-token 持久化到仓库或本地 settings.json。

Deliverables:
- 设置页新增 Claude SDK base-url 与 auth-token 配置入口。
- GUI 本地设置可保存 Claude SDK base-url，模型继续使用现有默认模型字段。
- 运行时环境同步逻辑。
- 对应测试与截图验证。

Done When:
- 设置页可以看到并编辑 Claude SDK base-url。
- 设置页可以输入 Claude SDK auth-token，但该值只保留在当前窗口内存。
- 如果设置了默认模型，Claude SDK 运行时可通过 `ANTHROPIC_MODEL` 读取到该值。
- 验证通过。

Validation:
- `uv run python -m app.main --help`
- `uv run pytest -q`
- `uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-claude-sdk-defaults.png"`

Review Gates:
- 避免修改 `app/llm/claude_client.py` 的调用协议；优先在 GUI 层完成设置注入。

