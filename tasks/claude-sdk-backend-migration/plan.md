# 里程碑计划

## Source of Truth / 事实来源

- 合同文件：`D:\code\bidreview\tasks\claude-sdk-backend-migration\contract.md`
- 生效中的 AGENTS 文件：`D:\code\bidreview\AGENTS.md`
- 已参考的仓库文档：`D:\code\bidreview\README.md`

## Goal Summary / 目标摘要

- Goal / 目标：
  - 将 `claude` 后端从客户机全局 CLI 依赖迁移到项目内官方 Claude Python SDK 运行时
- Desired Effect / 期望效果：
  - 降低客户部署前置条件，同时保持现有审查与报告导出契约基本稳定
- 关键约束：
  - 保持 CLI/报告兼容性
  - 不扩大到 OpenCode 生产重构
  - 受 AGENTS 评审关口约束，涉及新依赖与后端调用行为变更时必须显式确认
  - Claude SDK 配置优先复用 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_AUTH_TOKEN`

## Milestones / 里程碑

### Milestone 1 / 里程碑 1：基线与接入设计

- 覆盖的 Done When / 完成条件条目：
  - `README`/实现目标与运行前提被清晰定义
  - 运行时来源、认证方式、MCP 配置与失败提示方案明确
- 范围：
  - 复核当前 CLI 调用点、`LLMClient` 边界和 Anthropic SDK 能力
  - 固化接入设计、评审关口与验证清单
- 可能涉及的文件或模块：
  - `app/llm/claude_client.py`
  - `app/llm/client_factory.py`
  - `app/main.py`
  - `pyproject.toml`
  - `README.md`
  - `tasks/claude-sdk-backend-migration/*.md`
- 风险：
  - SDK 事件模型与现有 CLI 流式输出不完全一致
  - MCP/工具调用能力可能无法一比一平移

Acceptance Criteria / 验收标准：

- 已形成明确任务合同与里程碑计划
- 已识别会触发的评审关口和需要用户确认的关键决策
- 已列出后续实现所需最小模块集合和验证命令

Validation Commands / 验证命令：

- 命令：`uv run python -m app.main --help`
  原因：确认当前基线入口正常，后续可作为回归比较基准
  通过条件：命令返回码为 0，帮助信息可输出

Status / 状态：

- `completed`

### Milestone 2 / 里程碑 2：SDK 后端实现与接入

- 覆盖的 Done When / 完成条件条目：
  - `claude` 后端默认运行路径不再要求客户机预装全局 CLI
  - 审查链路保持可用，输出契约未发生未计划变化
- 范围：
  - 引入并集成官方 Claude Python SDK
  - 将现有 `LLMClient` 适配到新运行时
  - 处理可用性检查、错误信息、超时和最小必要进度输出
  - 将 SDK 默认配置源对齐到 `ANTHROPIC_*` 环境变量
- 可能涉及的文件或模块：
  - `pyproject.toml`
  - `app/llm/claude_client.py` 或新增 SDK 客户端文件
  - `app/llm/client_factory.py`
  - `app/main.py`
  - `tests/**`
- 风险：
  - 新依赖引入方式影响打包与安装
  - 旧参数如 `--claude-bin` 的去留会影响兼容策略
  - 可用性检测不再等同于 `claude --version`
  - Anthropic SDK/CLI 对 `ANTHROPIC_AUTH_TOKEN` 与自定义 `BASE_URL` 的支持细节需要按官方能力校验

Acceptance Criteria / 验收标准：

- 代码路径已改为项目内 SDK 运行时，而不是强依赖全局 `claude` 命令
- 现有 orchestrator/review 调用方式不需要大规模重写
- 新增或更新的测试覆盖关键适配行为

Validation Commands / 验证命令：

- 命令：`uv run pytest -q`
  原因：回归测试与新增测试校验
  通过条件：全部测试通过
- 命令：`uv run python -m app.main --help`
  原因：确保 CLI 入口不被依赖迁移破坏
  通过条件：返回码为 0
- 命令：在设置 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_AUTH_TOKEN` 后执行目标初始化/测试
  原因：验证新后端默认配置源正确
  通过条件：无需全局 `claude` CLI 配置即可读取环境变量并发起调用

Status / 状态：

- `completed`

### Milestone 3 / 里程碑 3：文档更新与烟测闭环

- 覆盖的 Done When / 完成条件条目：
  - 文档已更新并明确新部署方式
  - 合同定义的验证已实际完成
- 范围：
  - 更新 `README.md` 与必要说明
  - 执行 Claude 受影响链路的烟测并核对产物
- 可能涉及的文件或模块：
  - `README.md`
  - `data/output/run-*`（仅用于验证，不提交）
  - 必要时 `tests/**`
- 风险：
  - 缺少稳定可复用的本地样例文档会影响烟测
  - SDK 鉴权或客户环境模拟不足会影响“无需全局 CLI”证明力度

Acceptance Criteria / 验收标准：

- 文档已说明 SDK 集成方式、联网/鉴权前提和限制
- 至少一次本地烟测成功并核对关键输出文件
- `status.md` 中有完整验证记录与 blocker 状态

Validation Commands / 验证命令：

- 命令：一次 `uv run python -m app.main --backend claude ...`
  原因：验证核心链路在新后端下可运行
  通过条件：生成目标报告文件且无未计划报错
- 命令：如需补充，执行针对初始化/可用性的自检命令
  原因：证明项目内运行时替代全局 CLI 的目标成立
  通过条件：自检结果与合同目标一致

Status / 状态：

- `completed`

## Review Gates / 评审关口

- Gate / 关口：
  触发条件：新增官方 Claude Python SDK 作为生产依赖
  需要确认的决策：依赖名称、版本约束、是否保留旧 CLI 兼容路径
- Gate / 关口：
  触发条件：修改 `app/main.py` 参数或默认后端行为
  需要确认的决策：是否保留 `--claude-bin`，是否新增 `claude-sdk` 模式
- Gate / 关口：
  触发条件：SDK 无法覆盖当前工具/MCP/进度行为
  需要确认的决策：接受功能降级、双栈兼容，还是转向其他集成方式

## Gaps / 信息缺口

- 缺失信息：
  - 最终客户交付形式与安装方式
  - 是否需要在无全局 `claude` 命令的干净环境中做强证明
- 需要确认的假设：
  - 首阶段只替换 Claude，不扩到 OpenCode
  - 输出 JSON/Markdown/DOCX 契约必须保持兼容
  - 允许直接以 `ANTHROPIC_*` 作为默认配置源，而不是引入项目私有的 Claude 环境变量

## Exit Conditions / 退出条件

- 只有当每条 Done When 都被通过的验证覆盖，或已确认并记录明确 blocker 时，任务才可结束。
