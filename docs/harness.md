# Harness

## Purpose

仓库内 harness 提供统一、机器可执行的验证入口，覆盖 CLI、GUI smoke、triage、task docs 和 agent workspace 辅助。

## Entry Points

- CLI help
  - `uv run python -m app.main --help`
- Full pytest
  - `uv run pytest -q`
- Default harness suite
  - `uv run python scripts/run_harness.py --output-dir tmp/harness-full`
- Single run triage
  - `uv run python scripts/triage_run.py data/output/run-*/`

## Default Case Set

当前默认 case 定义位于 `harness/cases/`，包括：

- `cli-help`
  - 验证主 CLI 帮助入口仍可执行
- `gui-smoke`
  - 验证 GUI 可在 smoke-test 模式下启动并输出截图
- `triage-harness-fixture`
  - 验证 triage 能识别 harness run
- `triage-review-fixture`
  - 验证 triage 能识别 review run
- `task-doc-scaffold`
  - 验证 repo-local task doc 脚手架可生成文档六件套
- `agent-worktree-dry-run`
  - 验证 agent worktree helper 的 dry-run 输出

## Runner Output

每次 harness 运行会生成：

- `run_manifest.json`
  - 顶层 `kind=harness`
  - case 计数、失败计数、起止时间、每个 case 的输出路径
- `<case>/stdout.txt`
- `<case>/stderr.txt`
- `<case>/result.json`

默认输出目录：

- `tmp/harness-runs/run-<timestamp>/`

## Review Run Observability

review pipeline 现在也会额外输出：

- `run_manifest.json`
  - 顶层 `kind=review`
  - backend、review profile、隔离运行目录、阶段状态、错误摘要、每个 bid 的关键产物路径
- `batch_summary.json`

因此 triage 脚本可以统一摘要 harness run 和 review run。

## CI Usage

CI 当前至少执行：

- Python sources compile
- CLI help
- Default harness suite
- Full pytest

## Current Limits

- 还没有接入真实脱敏招投标样本集
- 还没有 golden-output 级别的结果比对
- 还没有外部日志/trace 查询层

这意味着当前 harness 已经覆盖 repo-native 工程回路，但还不是完整评测平台。
