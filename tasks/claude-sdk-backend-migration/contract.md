# 任务规格 / Success Contract

## Goal / 目标

将当前 `claude` 后端从“依赖客户环境预先安装并登录全局 `claude` CLI”的运行模式，迁移为“项目内直接集成官方 Claude Python SDK 运行时”的模式，减少客户部署前置条件，并保持现有审查流程与报告输出契约尽量稳定。

## Desired Effect / 期望效果

任务完成后：

- 在客户环境中部署本项目时，不再要求额外手工安装全局 `claude` CLI。
- `--backend claude` 仍可完成现有招投标审查流程，输出结构与报告产物保持兼容。
- 运行说明明确区分“本地 SDK/运行时集成”与“模型仍然远程调用 Anthropic 或兼容托管端点”。
- 本项目对 Claude 运行时、认证、MCP 配置与打包方式的控制更集中，不再强依赖用户主目录下的个人安装状态。

## Context / 上下文

- 仓库：`D:\code\bidreview`
- 相关模块：
  - `app/llm/claude_client.py`
  - `app/llm/client_factory.py`
  - `app/main.py`
  - `app/orchestrator.py`
  - `app/review/claude_review.py`
  - `pyproject.toml`
  - `README.md`
- 当前行为：
  - `claude` 后端通过 `subprocess` 调用客户机全局 `claude`/`claude.cmd`
  - 可执行文件解析依赖 PATH、环境变量或 Windows npm 全局目录
  - 可选复用 `--mcp-config` 与本机 Claude 相关配置
- 目标配置来源：
  - 使用系统环境变量 `ANTHROPIC_BASE_URL`
  - 使用系统环境变量 `ANTHROPIC_MODEL`
  - 使用系统环境变量 `ANTHROPIC_AUTH_TOKEN`
- 参考资料：
  - Anthropic Claude Agent SDK / Claude Code SDK 官方文档
  - Claude Code SDK for Python 官方仓库 README
  - 仓库现有 `AGENTS.md`、`README.md`

## Constraints / 约束

- 兼容性约束：
  - 尽量保持现有 CLI 参数和默认使用方式兼容
  - 尽量保持现有 JSON 解析、报告导出和 orchestrator 调用方式兼容
  - 不无故改变输出文件名、报告结构或 prompt 契约
- 性能约束：
  - 不显著恶化现有长任务的超时、流式进度和大文档处理体验
- 安全或数据约束：
  - 仍然以远程模型调用为前提，不引入“本地离线推理”误导
  - 认证信息应继续通过环境变量或受控配置传入，不写死到代码和脚本
  - Claude SDK 的模型/鉴权/网关配置优先使用 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_AUTH_TOKEN`
- 工具或环境约束：
  - 依赖管理继续使用 `uv`
  - 需要评估官方 Python SDK 是否足以覆盖当前 `claude` CLI 的事件流、工具调用、MCP 配置与超时控制

## Non-goals / 非目标

- 本次不同时完成 OpenCode SDK/Server 方案的生产级重构接入
- 本次不重写本地审查推理逻辑，仍保持 Claude 驱动
- 本次不做与该迁移无关的跨模块重构、命名整理或报告格式调整
- 本次不承诺实现完全离线、本地模型部署或无网运行

## Deliverables / 交付物

- 代码改动：
  - 一个基于官方 Claude Python SDK 的项目内 `claude` 后端实现
  - 与现有 `LLMClient` 抽象对齐的接入与工厂选择逻辑
  - 必要时保留兼容回退或显式失败提示
- 测试：
  - 覆盖新后端关键行为的最小必要测试
  - 至少一次受影响链路的本地验证
- 文档或配置：
  - 更新依赖与运行说明
  - 说明认证、联网前提、MCP 配置来源与打包约束
- 脚本或迁移：
  - 如有必要，补充最小自检脚本或验证说明，证明无需客户预装全局 `claude` CLI

## Done When / 完成条件

- `claude` 后端默认运行路径不再要求客户环境预先安装全局 `claude` CLI
- 现有 `--backend claude` 审查链路在迁移后仍能完成调用，并保持报告输出契约不发生未计划变化
- 代码中对 Claude 运行时来源、认证方式、MCP 配置与失败提示有清晰、可维护的实现
- Claude SDK 能从 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_AUTH_TOKEN` 完成默认配置，且行为可被文档说明
- `README.md` 与相关说明已更新，明确部署与打包方式的变化
- 所有合同内验证项已实际运行并通过，或 blocker 已被清晰记录

## Validation / 验证方式

- 命令：`uv run python -m app.main --help`
  预期结果：CLI 可正常启动，帮助信息可用，未因依赖变更损坏入口
- 命令：`uv run pytest -q`
  预期结果：现有测试与新增测试通过
- 命令：一次 `--backend claude` 的本地烟测
  预期结果：成功生成并核对 `review_result.json`、`review_report.md`、`review_report.docx`、`batch_summary.json`
- 命令：针对新后端的可用性/初始化自检
  预期结果：能够证明运行依赖来自项目内 SDK，而非客户机预装全局 `claude` CLI
- 命令：在设置 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_AUTH_TOKEN` 的环境下执行 Claude 后端初始化或烟测
  预期结果：无需额外 CLI 本地配置即可命中新环境变量并完成调用

## Review Gates / 评审关口

- 在以下情况下必须暂停确认：
  - 需要新增生产依赖（例如官方 Claude Python SDK）
  - 需要改变 `app/main.py` 参数契约或默认后端行为
  - 需要改变 `app/llm/` 中 Claude 调用、超时、MCP、工具调用或重试行为
  - 需要改变 prompt/output/report 契约或导出文件名
- 在以下变更前必须先问：
  - 是否保留旧的 `--claude-bin` 兼容路径
  - 是否需要引入新的后端名称，例如 `claude-sdk`
  - 如果 SDK 无法完整覆盖当前 CLI 行为，是否接受功能降级、双栈兼容或 sidecar 方案

## Notes / 备注

- 可选假设：
  - 首阶段优先替换 `claude` 后端，不同时处理 OpenCode 生产集成
  - 优先保持用户可见 CLI 参数与输出结构稳定
  - Claude SDK 默认从 `ANTHROPIC_*` 环境变量读取模型、认证与 base URL
- 待确认问题：
  - 客户交付形态是源码 + `uv sync`，还是单文件/目录打包产物
  - 是否必须保留现有进度流样式与工具调用明细输出
