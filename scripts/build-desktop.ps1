param(
    [switch]$Clean,
    [ValidateSet("onedir", "launcher", "standalone")]
    [string]$Mode = "onedir"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$NormalizedMode = if ($Mode -eq "standalone") { "onedir" } else { $Mode }

Set-Location $ProjectRoot

function Get-RunningBundleProcesses([string[]]$ExpectedExePaths) {
    $normalizedPaths = @{}
    foreach ($path in $ExpectedExePaths) {
        if (-not $path) {
            continue
        }
        $normalizedPaths[[System.IO.Path]::GetFullPath($path)] = $true
    }

    $matches = @()
    foreach ($process in (Get-Process -ErrorAction SilentlyContinue)) {
        $processPath = $null
        try {
            $processPath = $process.Path
        } catch {
            $processPath = $null
        }
        if (-not $processPath) {
            continue
        }
        $fullPath = [System.IO.Path]::GetFullPath($processPath)
        if ($normalizedPaths.ContainsKey($fullPath)) {
            $matches += $process
        }
    }
    return $matches
}

$runningBundles = Get-RunningBundleProcesses @(
    "$ProjectRoot\dist\BidReviewDesktop\BidReviewDesktop.exe",
    "$ProjectRoot\dist\BidReviewDesktopLauncher\BidReviewDesktopLauncher.exe",
    "$ProjectRoot\dist\BidReviewDesktopStandalone\BidReviewDesktopStandalone.exe"
)

if ($runningBundles.Count -gt 0) {
    Write-Error (
        "检测到旧版桌面 EXE 正在运行，请先关闭后再重新打包：" +
        [Environment]::NewLine +
        (($runningBundles | ForEach-Object { " - {0} (PID {1})" -f $_.Path, $_.Id }) -join [Environment]::NewLine)
    )
    exit 1
}

if ($Clean) {
    Remove-Item -Recurse -Force "$ProjectRoot\build\BidReviewDesktopLauncher" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\dist\BidReviewDesktopLauncher" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\build\BidReviewDesktop" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\dist\BidReviewDesktop" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\build\BidReviewDesktopStandalone" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\dist\BidReviewDesktopStandalone" -ErrorAction SilentlyContinue
}

uv sync --extra dev
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SpecPath = if ($NormalizedMode -eq "onedir") {
    "$ProjectRoot\scripts\bid_review_desktop.spec"
} else {
    "$ProjectRoot\scripts\bid_review_launcher.spec"
}

uv run --extra dev pyinstaller --noconfirm --clean $SpecPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($NormalizedMode -eq "onedir") {
    $PythonHome = (& uv run python -c "import sys; from pathlib import Path; print(Path(sys.base_prefix).resolve())").Trim()
    $PythonDlls = Join-Path $PythonHome "DLLs"

    foreach ($opensslName in @("libcrypto-3-x64.dll", "libssl-3-x64.dll")) {
        $source = Join-Path $PythonDlls $opensslName
        $target = Join-Path "$ProjectRoot\dist\BidReviewDesktop\_internal" $opensslName
        if (Test-Path $source) {
            Copy-Item -Force $source $target
        }
    }

    foreach ($icuPath in @(
        "$ProjectRoot\dist\BidReviewDesktop\_internal\icuuc.dll",
        "$ProjectRoot\dist\BidReviewDesktop\_internal\icudt73.dll"
    )) {
        Remove-Item $icuPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Desktop bundle ready:" -ForegroundColor Cyan
if ($NormalizedMode -eq "onedir") {
    Write-Host "  $ProjectRoot\dist\BidReviewDesktop\BidReviewDesktop.exe"
} else {
    Write-Host "  $ProjectRoot\dist\BidReviewDesktopLauncher\BidReviewDesktopLauncher.exe"
}
