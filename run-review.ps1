param(
    [string[]]$Input,
    [string]$Tender,
    [string[]]$Bid,
    [ValidateSet("claude", "opencode")]
    [string]$Backend = "claude",
    [string]$OutputDir = "data/output",
    [string]$ClaudeBin,
    [string]$OpenCodeBin,
    [string]$OpenCodeModel = "DeepSeek-V3.2",
    [string]$OpenCodeProvider = "ark",
    [string]$OpenCodeApiUrl = "https://ark.cn-beijing.volces.com/api/coding/v3",
    [string]$OpenCodeApiKey,
    [ValidateSet("low", "medium", "high")]
    [string]$Effort = "low",
    [ValidateSet("agent", "basic", "normal", "detailed", "events", "raw")]
    [string]$ProgressLevel = "agent",
    [switch]$NoProgress,
    [int]$TimeoutSec = 1800,
    [string]$Instruction,
    [string]$UserInstruction,
    [string]$McpConfig,
    [string]$Model,
    [switch]$NoRawOutput
)

$args = @(
    "run", "python", "-m", "app.main",
    "--backend", $Backend,
    "--output-dir", $OutputDir,
    "--effort", $Effort,
    "--progress-level", $ProgressLevel,
    "--timeout-sec", $TimeoutSec.ToString()
)

if ($Input) {
    foreach ($item in $Input) {
        $args += @("--input", $item)
    }
}

if ($Tender) { $args += @("--tender", $Tender) }
if ($Bid) {
    foreach ($item in $Bid) {
        $args += @("--bid", $item)
    }
}
if ($ClaudeBin) { $args += @("--claude-bin", $ClaudeBin) }
if ($OpenCodeBin) { $args += @("--opencode-bin", $OpenCodeBin) }
if ($OpenCodeModel) { $args += @("--opencode-model", $OpenCodeModel) }
if ($OpenCodeProvider) { $args += @("--opencode-provider", $OpenCodeProvider) }
if ($OpenCodeApiUrl) { $args += @("--opencode-api-url", $OpenCodeApiUrl) }
if ($OpenCodeApiKey) { $args += @("--opencode-api-key", $OpenCodeApiKey) }
if ($NoProgress) { $args += @("--no-progress") }
if ($Instruction) { $args += @("--instruction", $Instruction) }
if ($UserInstruction) { $args += @("--user-instruction", $UserInstruction) }
if ($McpConfig) { $args += @("--mcp-config", $McpConfig) }
if ($Model) { $args += @("--model", $Model) }
if ($NoRawOutput) { $args += @("--no-raw-output") }

& uv @args
exit $LASTEXITCODE
