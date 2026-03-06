param(
    [string[]]$Input,
    [string]$Tender,
    [string[]]$Bid,
    [string]$OutputDir = "data/output",
    [string]$ClaudeBin,
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
if ($NoProgress) { $args += @("--no-progress") }
if ($Instruction) { $args += @("--instruction", $Instruction) }
if ($UserInstruction) { $args += @("--user-instruction", $UserInstruction) }
if ($McpConfig) { $args += @("--mcp-config", $McpConfig) }
if ($Model) { $args += @("--model", $Model) }
if ($NoRawOutput) { $args += @("--no-raw-output") }

& uv @args
exit $LASTEXITCODE
