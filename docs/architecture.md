# Architecture

## Goal

本项目把招投标文件审查委托给 Claude/OpenCode 运行时，本地 Python 负责编排、约束、导出和桌面包装。

## Main Flow

1. `app/main.py`
   解析 CLI 参数，调用编排层。
2. `app/orchestrator.py`
   处理输入角色、运行隔离、批量执行、结果导出和批次汇总。
3. `app/review/workflows/legacy_engine.py`
   组装 prompt，驱动 requirements / findings / second pass 审查流程。
4. `app/ai/providers/*`
   集成 Claude SDK runtime 与 OpenCode SDK runtime。
5. `app/mcp_servers/*`
   提供 PDF/Word/OCR 的项目内置 MCP 能力。
6. `app/report/*`
   导出 `json / markdown / docx`。

## Runtime Layers

- Python runtime
  - 入口、参数、环境、路径、重试、产物管理
- Model runtime
  - 角色识别、requirements 提取、findings 判断
- MCP runtime
  - 文档结构化读取、图片提取、OCR
- Desktop runtime
  - PySide6 GUI、冻结态 EXE、portable runtime 资源

## Key Directories

- `app/`
  - 生产代码
- `tests/`
  - 自动化回归
- `scripts/`
  - 构建、手册、harness、文档检查等脚本
- `harness/`
  - 机器可执行的 harness cases 和预期目录
- `docs/`
  - 稳定仓库文档
- `tasks/`
  - 长任务文档与实现审计轨迹

## Debugging Anchors

- `data/output/run-*`
  - 一次审查的主要产物
- `claude_raw_output.txt`
  - 模型原始输出
- `run_metrics.json`
  - 应用侧聚合指标
- `tmp/harness-runs/run-*`
  - harness 执行结果与 `run_manifest.json`
