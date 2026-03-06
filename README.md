# Bid Review

本项目用于对“招标文件 + 投标文件”进行自动审查，遵循纯 CLI 编排模式。

下文命令中的文件路径均为占位示例，请替换为你本机的实际文件路径：

1. 本地项目只把文件路径和任务提示词交给 `claude` CLI。
2. 文档解析、招投标识别、硬性条款提取、逐条审查全部由 Claude 执行。
3. 本地项目只负责接收 Claude 返回 JSON，并导出 `markdown + json + docx` 报告。
4. 默认包含“主体名词上下文一致性校验”：会检查招标人/投标人/开户银行等名词是否出现在正确位置与正确主体语境中。

## 运行

先同步环境：

```bash
uv sync
```

然后运行（PowerShell）：

```powershell
uv run python -m app.main `
  --input "C:\path\to\tender-document.pdf" `
  --input "C:\path\to\bid-document.docx" `
  --output-dir "data/output"
```

或手动指定角色（PowerShell）：

```powershell
uv run python -m app.main `
  --tender "C:\path\to\tender-document.pdf" `
  --bid "C:\path\to\bid-document.docx" `
  --output-dir "data/output"
```

如果你使用 `cmd.exe`，再用 `^` 续行：

```bash
uv run python -m app.main ^
  --input C:\path\to\tender-document.pdf ^
  --input "C:\path\to\bid-document.docx" ^
  --output-dir data/output
```

或手动指定角色（cmd.exe）：

```bash
uv run python -m app.main ^
  --tender C:\path\to\tender-document.pdf ^
  --bid "C:\path\to\bid-document.docx" ^
  --output-dir data/output
```

也可以直接用 PowerShell 包装脚本（避免续行符差异）：

```powershell
.\run-review.ps1 -Input "C:\path\to\tender-document.pdf","C:\path\to\bid-document.docx" -OutputDir "data/output"
```

如不需要保存每次运行的原始文本（`claude_raw_output.txt`），可加：

```powershell
uv run python -m app.main --input "..." --input "..." --output-dir "data/output" --no-raw-output
```

## Codex 并行子智能体启动测试

项目内提供了 4 路并行测试子智能体配置，可复用地验证 README 启动链路。

- 子智能体配置：`config/subagents/startup-test-agents.json`
- 并行调度脚本：`scripts/run-startup-subagents.ps1`
- Skill 安装脚本：`scripts/install-codex-skill.ps1`

先安装项目 Skill 到全局 `~/.codex/skills`（一次即可）：

```powershell
.\scripts\install-codex-skill.ps1 -Force
```

再执行并行启动测试（仍然使用 README 的 `uv run python -m app.main` 链路）：

```powershell
.\scripts\run-startup-subagents.ps1 `
  -Tender "<招标文件路径>" `
  -Bid "<投标文件1路径>","<投标文件2路径>"
```

每次运行会在 `data/output/subagent-startup/subagents-<timestamp>/` 生成：

- `startup_subagent_report.json`（主线程汇总用）
- `startup_subagent_report.md`（人工查看）
- 每个子智能体的 `agent.log` 与各自 `run-*` 产物目录

## 清理无用产物

如果你做过大量临时分析，根目录可能堆积未跟踪的 `txt/json/log` 文件。可用下面脚本清理：

先预览（不删除）：

```powershell
.\scripts\cleanup-artifacts.ps1
```

实际清理（保留最近 10 个 `data/output/run-*`）：

```powershell
.\scripts\cleanup-artifacts.ps1 -Apply -KeepRuns 10
```

如果你确认根目录未跟踪的临时 `*.py` 也都不需要，可额外加：

```powershell
.\scripts\cleanup-artifacts.ps1 -Apply -KeepRuns 10 -IncludeRootPy
```

## 个人指令

你可以传“用户个人指令”，会和系统提示词一起传给 Claude。

命令行传入（PowerShell）：

```powershell
uv run python -m app.main `
  --input "C:\path\to\tender-document.pdf" `
  --input "C:\path\to\bid-document.docx" `
  --user-instruction "优先关注否决项；发现证据不足时标记 needs_manual；输出建议要可执行" `
  --output-dir "data/output"
```

也支持环境变量（适合长期默认偏好）：

```powershell
$env:BID_REVIEW_USER_INSTRUCTION = "优先检查资格与报价；证据必须带原文片段"
uv run python -m app.main --input "..." --input "..." --output-dir "data/output"
```

## 运行进度

默认使用 `agent` 进度模式，输出“现在在做什么 / 下一步 / 阶段成果 / 总耗时”，避免 `events/raw` 的噪声。

如需关闭进度输出，可加：

```powershell
uv run python -m app.main --input "..." --input "..." --no-progress
```

如需切到“工具调用级”进度，可加：

```powershell
uv run python -m app.main --input "..." --input "..." --progress-level normal
```

如需更详细进度（含工具参数与更多中间片段），可加：

```powershell
uv run python -m app.main --input "..." --input "..." --progress-level detailed
```

如需不做内容裁剪、尽量原样看 Claude CLI 的流式事件，可加：

```powershell
uv run python -m app.main --input "..." --input "..." --progress-level raw
```

如果你希望“看原始事件但别太吵”，可加：

```powershell
uv run python -m app.main --input "..." --input "..." --progress-level events
```

`events` 会保留原始流式事件，但过滤 `content_block_delta` 这类逐字碎片输出。  
日常使用建议保持默认 `agent`。

## 多投标文件

支持“1份招标文件 + 多份投标文件”批量审查。

手动指定（PowerShell）：

```powershell
uv run python -m app.main `
  --tender "C:\path\to\tender-document.pdf" `
  --bid "C:\path\to\bid-document.docx" `
  --bid "C:\path\to\bid-document-2.docx" `
  --output-dir "data/output"
```

自动识别（PowerShell）：

```powershell
uv run python -m app.main `
  --input "C:\path\to\tender-document.pdf" `
  --input "C:\path\to\bid-document.docx" `
  --input "C:\path\to\bid-document-2.docx" `
  --output-dir "data/output"
```

批量模式下会在本次 `run-xxx` 目录下为每个投标文件生成一个子目录，并输出汇总文件 `batch_summary.json`。

## 环境要求

- Python 3.10+
- `uv`（已用于环境和依赖管理）
- 本机已安装并可运行 `claude` CLI（`claude --version`）
- `claude` 侧已配置 PDF/Word/OCR 的 MCP（推荐）
- 已安装依赖（见 `pyproject.toml`）

## 说明

- 本项目不会在本地做条款抽取和审查判定，Claude 负责完整审查逻辑。
- 若 Claude 返回格式异常，程序会报错并保留 `claude_raw_output.txt` 便于排查。
- 默认不显式指定模型，直接使用你本机 Claude CLI 已配置的默认模型；如需临时覆盖可传 `--model`。
- 提示词已配置化，位于 `app/llm/prompts/`（可直接修改模板）。
- 可通过环境变量 `BID_REVIEW_PROMPTS_DIR` 指向自定义提示词目录（文件名需保持一致）。
