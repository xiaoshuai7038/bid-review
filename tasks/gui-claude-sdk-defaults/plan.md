Milestone 1: Settings Model
- Acceptance:
  - `DesktopSettings` 能承接 Claude SDK base-url。
  - 现有默认模型字段可默认读取 `ANTHROPIC_MODEL`。

Milestone 2: Settings UI
- Acceptance:
  - 设置页出现 Claude SDK base-url 与 auth-token 字段。
  - auth-token 为密码输入，且有“不持久化”提示。

Milestone 3: Runtime Wiring + Validation
- Acceptance:
  - GUI 启动或保存设置后，会把 Claude SDK 配置同步到进程环境。
  - 测试覆盖字段加载/持久化边界。
  - smoke screenshot 可见配置区。

