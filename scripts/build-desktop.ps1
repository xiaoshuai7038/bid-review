param(
    [switch]$Clean,
    [ValidateSet("onedir", "launcher", "standalone")]
    [string]$Mode = "onedir",
    [string]$PortableGitRoot = "",
    [string]$NodeRuntimeRoot = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$NormalizedMode = if ($Mode -eq "standalone") { "onedir" } else { $Mode }

Set-Location $ProjectRoot

function Get-RunningBundleProcesses([string[]]$ExpectedExePaths, [string[]]$ExpectedRoots) {
    $normalizedPaths = @{}
    foreach ($path in $ExpectedExePaths) {
        if (-not $path) {
            continue
        }
        $normalizedPaths[[System.IO.Path]::GetFullPath($path)] = $true
    }

    $normalizedRoots = @()
    foreach ($root in $ExpectedRoots) {
        if (-not $root) {
            continue
        }
        $fullRoot = [System.IO.Path]::GetFullPath($root).TrimEnd('\')
        if (-not $fullRoot) {
            continue
        }
        $normalizedRoots += $fullRoot
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
        $isMatch = $normalizedPaths.ContainsKey($fullPath)
        if (-not $isMatch) {
            foreach ($root in $normalizedRoots) {
                if ($fullPath.StartsWith($root + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
                    $isMatch = $true
                    break
                }
            }
        }
        if ($isMatch) {
            $matches += $process
        }
    }
    return $matches
}

function Get-GitRuntimeRoot([string]$ExplicitRoot) {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($ExplicitRoot)) {
        $candidates += $ExplicitRoot
    } else {
        try {
            $gitCommand = Get-Command git -ErrorAction Stop
            if ($gitCommand.Source) {
                $candidates += $gitCommand.Source
            }
        } catch {
            $candidates = @()
        }
    }

    foreach ($candidate in $candidates) {
        if (-not $candidate) {
            continue
        }
        $path = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path $path -PathType Leaf) {
            $path = Split-Path -Parent $path
        }
        $current = [System.IO.DirectoryInfo]::new($path)
        while ($null -ne $current) {
            $bashPath = Join-Path $current.FullName "bin\bash.exe"
            if (Test-Path $bashPath -PathType Leaf) {
                return $current.FullName
            }
            $current = $current.Parent
        }
    }
    return $null
}

function Get-NodeRuntimeRoot([string]$ExplicitRoot) {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($ExplicitRoot)) {
        $candidates += $ExplicitRoot
    } else {
        try {
            $nodeCommand = Get-Command node -ErrorAction Stop
            if ($nodeCommand.Source) {
                $candidates += $nodeCommand.Source
            }
        } catch {
            $candidates = @()
        }
    }

    foreach ($candidate in $candidates) {
        if (-not $candidate) {
            continue
        }
        $path = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path $path -PathType Leaf) {
            $path = Split-Path -Parent $path
        }
        $nodeExe = Join-Path $path "node.exe"
        if (Test-Path $nodeExe -PathType Leaf) {
            return $path
        }
    }
    return $null
}

function Invoke-RobocopyMirror([string]$Source, [string]$Target) {
    $null = New-Item -ItemType Directory -Path $Target -Force
    robocopy $Source $Target /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy copy failed, exit code: $LASTEXITCODE"
    }
}

function Stage-PortableGitRuntime([string]$SourceRoot, [string]$TargetRoot) {
    Invoke-RobocopyMirror -Source $SourceRoot -Target $TargetRoot

    $gitExe = Join-Path $TargetRoot "cmd\git.exe"
    $gitVersion = ""
    if (Test-Path $gitExe -PathType Leaf) {
        try {
            $gitVersion = (& $gitExe --version 2>$null).Trim()
        } catch {
            $gitVersion = ""
        }
    }

    $metadata = @(
        "Bundled by BidReview desktop build",
        "SourceRoot: $SourceRoot",
        ("GitVersion: " + ($(if ($gitVersion) { $gitVersion } else { "unknown" }))),
        ("PreparedAt: " + [DateTime]::Now.ToString("yyyy-MM-dd HH:mm:ss"))
    ) -join [Environment]::NewLine
    Set-Content -Path (Join-Path $TargetRoot "BID_REVIEW_PORTABLE_GIT.txt") -Value $metadata -Encoding UTF8
}

function Stage-NodeRuntime([string]$SourceRoot, [string]$TargetRoot) {
    Invoke-RobocopyMirror -Source $SourceRoot -Target $TargetRoot

    $nodeExe = Join-Path $TargetRoot "node.exe"
    $nodeVersion = ""
    if (Test-Path $nodeExe -PathType Leaf) {
        try {
            $nodeVersion = (& $nodeExe --version 2>$null).Trim()
        } catch {
            $nodeVersion = ""
        }
    }

    $metadata = @(
        "Bundled by BidReview desktop build",
        "SourceRoot: $SourceRoot",
        ("NodeVersion: " + ($(if ($nodeVersion) { $nodeVersion } else { "unknown" }))),
        ("PreparedAt: " + [DateTime]::Now.ToString("yyyy-MM-dd HH:mm:ss"))
    ) -join [Environment]::NewLine
    Set-Content -Path (Join-Path $TargetRoot "BID_REVIEW_BUNDLED_NODE.txt") -Value $metadata -Encoding UTF8
}

function Stage-OpenCodeRuntime([string]$ProjectRoot, [string]$TargetRoot) {
    $requiredPaths = @(
        "$ProjectRoot\node_modules\@opencode-ai\sdk",
        "$ProjectRoot\node_modules\opencode-ai",
        "$ProjectRoot\node_modules\.bin",
        "$ProjectRoot\app\ai\providers\opencode\bridge"
    )

    foreach ($path in $requiredPaths) {
        if (-not (Test-Path $path)) {
            throw "Missing required OpenCode runtime path for desktop packaging: $path. Run npm install first."
        }
    }

    $optionalPaths = @(
        "$ProjectRoot\node_modules\opencode-windows-x64",
        "$ProjectRoot\node_modules\opencode-windows-x64-baseline",
        "$ProjectRoot\node_modules\opencode-windows-arm64"
    )

    $copyMap = @(
        @{ Source = "$ProjectRoot\node_modules\@opencode-ai"; Target = Join-Path $TargetRoot "node_modules\@opencode-ai" },
        @{ Source = "$ProjectRoot\node_modules\opencode-ai"; Target = Join-Path $TargetRoot "node_modules\opencode-ai" },
        @{ Source = "$ProjectRoot\node_modules\.bin"; Target = Join-Path $TargetRoot "node_modules\.bin" },
        @{ Source = "$ProjectRoot\app\ai\providers\opencode\bridge"; Target = Join-Path $TargetRoot "bridge" }
    )
    foreach ($path in $optionalPaths) {
        $name = Split-Path -Leaf $path
        $copyMap += @{ Source = $path; Target = Join-Path $TargetRoot "node_modules\$name" }
    }

    foreach ($item in $copyMap) {
        $path = [string]$item.Source
        $targetPath = [string]$item.Target
        if (-not (Test-Path $path)) {
            continue
        }
        if (Test-Path $path -PathType Container) {
            Invoke-RobocopyMirror -Source $path -Target $targetPath
        } else {
            $targetDir = Split-Path -Parent $targetPath
            $null = New-Item -ItemType Directory -Path $targetDir -Force
            Copy-Item -Force $path $targetPath
        }
    }

    $metadata = @(
        "Bundled by BidReview desktop build",
        ("PreparedAt: " + [DateTime]::Now.ToString("yyyy-MM-dd HH:mm:ss")),
        "RuntimePaths:",
        " - node_modules\\@opencode-ai",
        " - node_modules\\opencode-ai",
        " - node_modules\\.bin",
        " - bridge",
        " - optional opencode-windows-* packages if present"
    ) -join [Environment]::NewLine
    Set-Content -Path (Join-Path $TargetRoot "BID_REVIEW_BUNDLED_OPENCODE.txt") -Value $metadata -Encoding UTF8
}

function Remove-BuildTarget([string]$Path) {
    if (-not $Path) {
        return
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    if (Test-Path -LiteralPath $Path -PathType Container) {
        cmd.exe /c "if exist `"$Path`" rmdir /s /q `"$Path`"" | Out-Null
    } else {
        cmd.exe /c "if exist `"$Path`" del /f /q `"$Path`"" | Out-Null
    }
    if (Test-Path -LiteralPath $Path) {
        throw "Failed to remove build target: $Path"
    }
}

$runningBundles = Get-RunningBundleProcesses @(
    "$ProjectRoot\dist\BidReviewDesktop\BidReviewDesktop.exe",
    "$ProjectRoot\dist\BidReviewDesktop\BidReviewRuntimeHost.exe",
    "$ProjectRoot\dist\BidReviewDesktop\BidReviewDesktop\BidReviewDesktop.exe",
    "$ProjectRoot\dist\BidReviewDesktop\BidReviewDesktop\BidReviewRuntimeHost.exe",
    "$ProjectRoot\dist\BidReviewDesktopLauncher\BidReviewDesktopLauncher.exe",
    "$ProjectRoot\dist\BidReviewDesktopStandalone\BidReviewDesktopStandalone.exe"
) @(
    "$ProjectRoot\dist\BidReviewDesktop",
    "$ProjectRoot\dist\BidReviewDesktopLauncher",
    "$ProjectRoot\dist\BidReviewDesktopStandalone"
)

if ($runningBundles.Count -gt 0) {
    Write-Error (
        "A previous desktop EXE is still running. Close it before rebuilding:" +
        [Environment]::NewLine +
        (($runningBundles | ForEach-Object { " - {0} (PID {1})" -f $_.Path, $_.Id }) -join [Environment]::NewLine)
    )
    exit 1
}

if ($Clean) {
    Remove-Item -Recurse -Force "$ProjectRoot\build\BidReviewDesktopLauncher" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\dist\BidReviewDesktopLauncher" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\build\BidReviewDesktop" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\build\portable-git" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\build\portable-nodejs" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$ProjectRoot\build\portable-opencode" -ErrorAction SilentlyContinue
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

$PrecleanTargets = if ($NormalizedMode -eq "onedir") {
    @(
        "$ProjectRoot\build\bid_review_desktop",
        "$ProjectRoot\build\portable-git",
        "$ProjectRoot\build\portable-nodejs",
        "$ProjectRoot\build\portable-opencode",
        "$ProjectRoot\dist\BidReviewDesktop",
        "$ProjectRoot\dist\BidReviewDesktop.zip"
    )
} else {
    @(
        "$ProjectRoot\build\bid_review_launcher",
        "$ProjectRoot\dist\BidReviewDesktopLauncher"
    )
}

foreach ($targetPath in $PrecleanTargets) {
    Remove-BuildTarget $targetPath
}

uv run --extra dev pyinstaller --noconfirm --clean $SpecPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($NormalizedMode -eq "onedir") {
    $gitRuntimeRoot = Get-GitRuntimeRoot $PortableGitRoot
    if (-not $gitRuntimeRoot) {
        Write-Error (
            "Unable to find a Git Bash runtime for packaging. Install Git for Windows " +
            "or use -PortableGitRoot to point to a Git root that contains bin\\bash.exe."
        )
        exit 1
    }

    $nodeRuntimeRoot = Get-NodeRuntimeRoot $NodeRuntimeRoot
    if (-not $nodeRuntimeRoot) {
        Write-Error (
            "Unable to find a Node.js runtime for packaging OpenCode. Install Node.js " +
            "or use -NodeRuntimeRoot to point to a directory that contains node.exe."
        )
        exit 1
    }

    $PythonHome = (& uv run python -c "import sys; from pathlib import Path; print(Path(sys.base_prefix).resolve())").Trim()
    $PythonDlls = Join-Path $PythonHome "DLLs"
    $PortableGitStageRoot = Join-Path "$ProjectRoot\build\portable-git" "git"
    $PortableNodeStageRoot = Join-Path "$ProjectRoot\build\portable-nodejs" "nodejs"
    $PortableOpenCodeStageRoot = Join-Path "$ProjectRoot\build\portable-opencode" "opencode"

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

    Remove-Item -Recurse -Force $PortableGitStageRoot -ErrorAction SilentlyContinue
    Stage-PortableGitRuntime -SourceRoot $gitRuntimeRoot -TargetRoot $PortableGitStageRoot

    $PortableGitDistRoot = Join-Path "$ProjectRoot\dist\BidReviewDesktop\third-party" "git"
    Remove-Item -Recurse -Force $PortableGitDistRoot -ErrorAction SilentlyContinue
    Stage-PortableGitRuntime -SourceRoot $PortableGitStageRoot -TargetRoot $PortableGitDistRoot

    Remove-Item -Recurse -Force $PortableNodeStageRoot -ErrorAction SilentlyContinue
    Stage-NodeRuntime -SourceRoot $nodeRuntimeRoot -TargetRoot $PortableNodeStageRoot
    $PortableNodeDistRoot = Join-Path "$ProjectRoot\dist\BidReviewDesktop\third-party" "nodejs"
    Remove-Item -Recurse -Force $PortableNodeDistRoot -ErrorAction SilentlyContinue
    Stage-NodeRuntime -SourceRoot $PortableNodeStageRoot -TargetRoot $PortableNodeDistRoot

    Remove-Item -Recurse -Force $PortableOpenCodeStageRoot -ErrorAction SilentlyContinue
    Stage-OpenCodeRuntime -ProjectRoot $ProjectRoot -TargetRoot $PortableOpenCodeStageRoot
    $PortableOpenCodeDistRoot = Join-Path "$ProjectRoot\dist\BidReviewDesktop\third-party" "opencode"
    Remove-Item -Recurse -Force $PortableOpenCodeDistRoot -ErrorAction SilentlyContinue
    Stage-OpenCodeRuntime -ProjectRoot $ProjectRoot -TargetRoot $PortableOpenCodeDistRoot
}

Write-Host ""
Write-Host "Desktop bundle ready:" -ForegroundColor Cyan
if ($NormalizedMode -eq "onedir") {
    Write-Host "  $ProjectRoot\dist\BidReviewDesktop\BidReviewDesktop.exe"
} else {
    Write-Host "  $ProjectRoot\dist\BidReviewDesktopLauncher\BidReviewDesktopLauncher.exe"
}
