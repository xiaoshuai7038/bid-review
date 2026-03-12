# Bid Review

本项目用于对“招标文件 + 投标文件”进行自动审查，遵循纯 CLI 编排模式。

下文命令中的文件路径均为占位示例，请替换为你本机的实际文件路径：

1. 本地项目把文件路径和任务提示词交给 Claude SDK 运行时或 OpenCode CLI（默认 `claude`，可切换 `opencode`）。
2. 文档解析、招投标识别、硬性条款提取、逐条审查全部由所选后端执行。
3. 本地项目只负责接收返回 JSON，并导出 `markdown + json + docx` 报告。
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

默认后端是 `claude`。如需显式指定：

```powershell
uv run python -m app.main `
  --backend claude `
  --input "C:\path\to\tender-document.pdf" `
  --input "C:\path\to\bid-document.docx" `
  --output-dir "data/output"
```

`claude` 后端现已通过项目依赖内置的 Claude Agent SDK 运行，不再要求客户环境额外全局安装 `claude` CLI。
项目会默认挂载仓库内统一管理的 MCP 能力：

- `document-parser`
- `paddle-ocr`

这两项能力由项目代码直接托管，不再依赖客户机手工维护 `~/.claude/mcp/*.json`。
默认会优先读取以下环境变量：

```powershell
$env:ANTHROPIC_AUTH_TOKEN = "<your-token>"
$env:ANTHROPIC_MODEL = "claude-sonnet-4-5"
$env:ANTHROPIC_BASE_URL = "https://api.anthropic.com"
```

- `ANTHROPIC_AUTH_TOKEN`：推荐，作为 Claude SDK/运行时的默认鉴权来源
- `ANTHROPIC_MODEL`：可选，作为 `claude` 后端默认模型
- `ANTHROPIC_BASE_URL`：可选，自定义 Claude API 网关地址
- `OCRMCP_BACKEND_URL`：可选，覆盖项目内 OCR MCP bridge 的远端服务地址
- `OCRMCP_API_KEY`：可选，远端 OCR 服务鉴权

如需显式覆盖 Claude Code 可执行文件路径，仍可继续传 `--claude-bin`；未传时默认使用 SDK 自带 bundled CLI。

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

## 桌面端 GUI

项目现已提供 Windows 桌面 GUI MVP，复用现有 `run_pipeline` 与报告导出链路，不替换 CLI。

开发态启动：

```powershell
uv run python -m app.gui.main
```

GUI 功能范围：

- 选择 1 份招标文件 + 1..N 份投标文件
- 配置 `claude / opencode`、模型、进度级别、输出目录、补充指令
- 后台执行审查并查看进度时间线 / 运行日志
- 查看 `summary / findings`
- 直接打开 `review_report.json / review_report.md / review_report.docx / batch_summary.json`

GUI 开发态本地设置默认保存在系统 AppData 目录，不写入仓库。
冻结态（打包后的 EXE）默认会把本项目自有运行产物写入 EXE 同级的 `runtime/` 目录，例如：

- `runtime/output/`
- `runtime/settings/`
- `runtime/tmp/document-parser/`
- `runtime/tmp/ocr/`

如需显式覆盖运行目录根，可设置：

```powershell
$env:BID_REVIEW_RUNTIME_ROOT = "D:\BidReviewDesktop\runtime"
```

如需做无头 smoke test 并截图：

```powershell
uv run python -m app.gui.main --smoke-test --screenshot "data/output/gui-smoke.png"
```

使用 OpenCode 后端（PowerShell）：

```powershell
uv run python -m app.main `
  --backend opencode `
  --input "C:\path\to\tender-document.pdf" `
  --input "C:\path\to\bid-document.docx" `
  --opencode-provider "volcengine" `
  --opencode-api-url "https://ark.cn-beijing.volces.com/api/coding/v3" `
  --opencode-model "DeepSeek-V3.2" `
  --opencode-api-key "<your-api-key>" `
  --output-dir "data/output"
```

默认情况下，`--backend opencode` 也会优先使用仓库内统一管理的 MCP 配置。
如需显式指定，也可以继续传 `--mcp-config`（支持 Claude 风格 `mcpServers` JSON）；显式传入时会覆盖项目默认配置。

如不需要保存每次运行的原始文本（`claude_raw_output.txt`），可加：

```powershell
uv run python -m app.main --input "..." --input "..." --output-dir "data/output" --no-raw-output
```

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

如需不做内容裁剪、尽量原样看 Claude SDK 内部 Claude Code 运行时的流式事件，可加：

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

## 打包桌面 EXE

桌面端采用 `PySide6`。

当前默认推荐的是客户可交付的稳定 `onedir` 包。
该产物不依赖仓库源码、`.venv`、`uv` 或本地 Python，适合直接交付到新的 Windows 客户机。
桌面包会同时内置：

- `Claude Agent SDK` 所需的 bundled `claude.exe`
- 项目内置 MCP 的 runtime host：`BidReviewRuntimeHost.exe`
- 供 `Claude Code` 在 Windows 上使用的 portable Git Bash runtime：`third-party\git\`

其中 `BidReviewRuntimeHost.exe` 仅供桌面程序在后台拉起 `document-parser` / `paddle-ocr` MCP 使用，用户无需手动启动。
Windows 客户机默认无需再单独安装 Git for Windows；桌面包会优先使用包内 `third-party\git\bin\bash.exe`。
如需手工覆盖，也可显式设置：

```powershell
$env:CLAUDE_CODE_GIT_BASH_PATH = "C:\Program Files\Git\bin\bash.exe"
```

首期客户交付范围：

- 仅支持 `Claude` 后端
- `ANTHROPIC_AUTH_TOKEN`、模型、base URL 等参数由用户在 GUI 中自行配置
- 不处理 `OpenCode` 的客户交付、CLI 分发或运行保障

执行：

```powershell
.\scripts\build-desktop.ps1
```

产物路径：

```text
dist\BidReviewDesktop\BidReviewDesktop.exe
```

如果需要先清理旧产物：

```powershell
.\scripts\build-desktop.ps1 -Clean
```

如果你正在运行旧版 `BidReviewDesktop.exe` 或 `BidReviewDesktopLauncher.exe`，请先关闭后再重新打包；脚本会在检测到旧进程占用时直接报错退出。

如果你需要兼容旧命令，`standalone` 仍然作为别名保留：

```powershell
.\scripts\build-desktop.ps1 -Mode standalone
```

产物路径仍然是：

```text
dist\BidReviewDesktop\BidReviewDesktop.exe
```

如需继续生成仓库内开发使用的 repo-local launcher，可显式指定：

```powershell
.\scripts\build-desktop.ps1 -Mode launcher
```

launcher 路径：

```text
dist\BidReviewDesktopLauncher\BidReviewDesktopLauncher.exe
```

`launcher` 依赖仓库根目录和 `.venv`，只适合项目开发或内部调试，不适合直接交付客户。

### portable Git 来源

默认打包流程会优先从当前构建机已安装的 Git for Windows 根目录准备 portable Git runtime，
再将其复制到桌面交付目录的 `third-party\git\`。

如当前构建机上的 Git 不在常见位置，可显式传入：

```powershell
.\scripts\build-desktop.ps1 -PortableGitRoot "C:\Program Files\Git"
```

打包后的 `third-party\git\` 会保留 Git 自带许可证文件，并额外生成：

```text
third-party\git\BID_REVIEW_PORTABLE_GIT.txt
```

用于记录本次打包使用的 Git 来源路径与版本。

### 运行期目录说明

冻结态 `BidReviewDesktop.exe` 默认会优先将本项目自有运行产物写入 EXE 同级目录下的 `runtime/` 子目录，而不是：

- `Documents\BidReview\output`
- `%LOCALAPPDATA%\Temp\word_images_*`
- `%LOCALAPPDATA%\Temp\ocr_upload_*`
- `%LOCALAPPDATA%\Temp\ocr_pdf_pages_*`

当前默认治理范围仅覆盖本项目自有路径：

- 审查结果输出
- GUI 设置文件
- Word 图片提取临时目录
- OCR 上传缓存与 PDF 渲染临时目录

对于第三方运行时目录：

- Claude Code / Claude SDK 运行时的 `~/.claude/projects/.../tool-results`
- OpenCode 自身的 storage/cache/log

项目会尽量提供实验性配置入口，但不保证所有第三方目录都能完全迁离用户目录；实际能力以所用运行时版本是否支持为准。

实验性可验证入口：

```powershell
$env:CLAUDE_CONFIG_DIR = "D:\BidReviewDesktop\runtime\third-party\claude"
```

OpenCode 侧当前会尝试向内联配置中注入：

```json
{
  "data": {
    "directory": "D:/BidReviewDesktop/runtime/third-party/opencode/data"
  }
}
```

但这部分不是默认开启：

- 当前版本 OpenCode 在真实实验中会对 `data` 键报错：`Unrecognized key: "data"`
- 因此项目仅保留实验性开关，不默认注入

如需自行验证，可显式开启：

```powershell
$env:BID_REVIEW_ENABLE_OPENCODE_DATA_DIRECTORY = "1"
```

是否会影响 OpenCode 的全部 project storage/cache/log，仍需以真实运行验证为准。

## 环境要求

以下要求针对源码开发、CLI 运行和本地重新打包；不适用于已经构建好的客户交付 `onedir` 桌面包。
客户机直接运行 `dist\BidReviewDesktop\BidReviewDesktop.exe` 时，不需要额外安装 Python、`uv`、仓库源码或全局 `claude` CLI。

- Python 3.10+
- `uv`（已用于环境和依赖管理）
- `claude` 后端无需额外全局安装 `claude` CLI；执行 `uv sync` 后会安装项目依赖中的 `claude-agent-sdk`
- 若重新打包桌面交付包，构建机需能提供 Git for Windows runtime（默认会自动探测本机 Git 安装目录，或通过 `-PortableGitRoot` 指定）
- 使用 `claude` 后端时，需配置 `ANTHROPIC_AUTH_TOKEN`
- 可选：`ANTHROPIC_MODEL`
- 可选：`ANTHROPIC_BASE_URL`
- 如使用 OpenCode 后端：本机已安装并可运行 `opencode` CLI（`opencode --version`）
- 如使用 OpenCode 后端并希望复用 OCR/PDF/Word 工具：本机已安装对应 Claude MCP，或通过 `--mcp-config` 显式传入
- `claude` 侧已配置 PDF/Word/OCR 的 MCP（推荐）
- 已安装依赖（见 `pyproject.toml`）

## 说明

- 本项目不会在本地做条款抽取和审查判定，所选后端负责完整审查逻辑。
- 若后端返回格式异常，程序会报错并保留 `claude_raw_output.txt` 便于排查。
- 默认后端是 `claude`；可用 `--backend opencode` 切换。
- 默认不显式指定 Claude 模型参数时，会优先读取 `ANTHROPIC_MODEL`；如需临时覆盖可传 `--model`。
- `claude` 后端通过项目内置 Claude Agent SDK 调远端模型，不是本地离线推理。
- 默认不显式指定 OpenCode 模型与网关时，沿用你本机 OpenCode 已配置的默认值；如需临时覆盖，可传 `--opencode-provider/--opencode-api-url/--opencode-model/--opencode-api-key`。
- 提示词已配置化，位于 `app/llm/prompts/`（可直接修改模板）。
- 可通过环境变量 `BID_REVIEW_PROMPTS_DIR` 指向自定义提示词目录（文件名需保持一致）。
